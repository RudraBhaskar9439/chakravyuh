"""Schema-constrained Gemini diagnosis with deterministic downstream guards."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from google import genai
from pydantic import ValidationError

from chakravyuh.config import Settings
from chakravyuh.domain.diagnoses import (
    DiagnosisDecision,
    DiagnosisReceipt,
    diagnosis_prompt,
    guard_diagnosis,
)
from chakravyuh.domain.errors import DiagnosisErrorCode, DiagnosisProcessingError
from chakravyuh.domain.evidence import EvidenceSubgraph


class GeminiStructuredDiagnostician:
    """Ask Gemini for a data-only proposal; never provide tools or execution authority."""

    provider = "gemini"

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self.model = settings.gemini_model
        self._timeout_seconds = settings.gemini_timeout_seconds
        self._minimum_confidence = settings.diagnosis_minimum_confidence
        if client is not None:
            self._client = client
        else:
            api_key = settings.gemini_api_key
            if api_key is None:
                msg = "GEMINI_API_KEY is required by the diagnosis worker"
                raise RuntimeError(msg)
            self._client = genai.Client(
                api_key=api_key.get_secret_value(),
                http_options={"api_version": "v1"},
            )

    async def diagnose(self, evidence: EvidenceSubgraph) -> DiagnosisReceipt:
        prompt, prompt_hash = diagnosis_prompt(evidence)
        try:
            interaction = await asyncio.wait_for(
                self._client.aio.interactions.create(
                    model=self.model,
                    input=prompt,
                    stream=False,
                    store=False,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": DiagnosisDecision.model_json_schema(),
                    },
                    generation_config={
                        "max_output_tokens": 2_048,
                        "seed": 7,
                        "thinking_level": "low",
                    },
                    timeout=self._timeout_seconds,
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as failure:
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.MODEL_TIMEOUT,
                retryable=True,
            ) from failure
        except Exception as failure:
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.MODEL_UNAVAILABLE,
                retryable=True,
            ) from failure

        if getattr(interaction, "status", None) != "completed":
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.MODEL_INCOMPLETE,
                retryable=True,
            )
        output_text = getattr(interaction, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.MODEL_INCOMPLETE,
                retryable=True,
            )
        try:
            decision = DiagnosisDecision.model_validate_json(output_text)
        except (ValidationError, ValueError) as failure:
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.MODEL_INVALID_RESPONSE,
                retryable=True,
            ) from failure
        guarded = guard_diagnosis(
            evidence,
            decision,
            minimum_confidence=self._minimum_confidence,
        )
        interaction_id = getattr(interaction, "id", None)
        return DiagnosisReceipt(
            model=self.model,
            provider_interaction_id=(
                interaction_id if isinstance(interaction_id, str) and interaction_id else None
            ),
            prompt_hash=prompt_hash,
            evidence_subgraph=evidence,
            diagnosis=guarded,
            diagnosed_at=datetime.now(UTC),
        )

    async def close(self) -> None:
        await self._client.aio.aclose()
