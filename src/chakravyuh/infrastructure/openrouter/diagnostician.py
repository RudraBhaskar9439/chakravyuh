"""Schema-constrained OpenRouter diagnosis with deterministic downstream guards."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
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

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterStructuredDiagnostician:
    """Ask OpenRouter for a data-only proposal with strict provider constraints."""

    provider = "openrouter"

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self.model = settings.openrouter_model
        self._timeout_seconds = settings.openrouter_timeout_seconds
        self._minimum_confidence = settings.diagnosis_minimum_confidence
        if client is not None:
            self._client = client
        else:
            api_key = settings.openrouter_api_key
            if api_key is None:
                msg = "CHAKRAVYUH_OPENROUTER_API_KEY is required by the diagnosis worker"
                raise RuntimeError(msg)
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout_seconds,
            )

    async def diagnose(self, evidence: EvidenceSubgraph) -> DiagnosisReceipt:
        prompt, prompt_hash = diagnosis_prompt(evidence)
        try:
            response = await asyncio.wait_for(
                self._client.post(
                    _ENDPOINT,
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "temperature": 0,
                        "seed": 7,
                        "max_tokens": 2_048,
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "diagnosis_decision",
                                "strict": True,
                                "schema": DiagnosisDecision.model_json_schema(),
                            },
                        },
                        "provider": {
                            "require_parameters": True,
                            "data_collection": "deny",
                        },
                    },
                ),
                timeout=self._timeout_seconds,
            )
        except (TimeoutError, httpx.TimeoutException) as failure:
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.MODEL_TIMEOUT,
                retryable=True,
            ) from failure
        except httpx.HTTPError as failure:
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.MODEL_UNAVAILABLE,
                retryable=True,
            ) from failure
        except Exception as failure:
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.MODEL_UNAVAILABLE,
                retryable=True,
            ) from failure

        if response.status_code < 200 or response.status_code >= 300:
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.MODEL_UNAVAILABLE,
                retryable=True,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as failure:
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.MODEL_INVALID_RESPONSE,
                retryable=True,
            ) from failure
        output_text, interaction_id, effective_model = _completion(payload)
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
        return DiagnosisReceipt(
            model=_model_label(effective_model),
            provider_interaction_id=interaction_id,
            prompt_hash=prompt_hash,
            evidence_subgraph=evidence,
            diagnosis=guarded,
            diagnosed_at=datetime.now(UTC),
        )

    async def close(self) -> None:
        await self._client.aclose()


def _completion(payload: object) -> tuple[str, str | None, str]:
    if not isinstance(payload, dict):
        raise DiagnosisProcessingError(
            DiagnosisErrorCode.MODEL_INVALID_RESPONSE,
            retryable=True,
        )
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise DiagnosisProcessingError(
            DiagnosisErrorCode.MODEL_INCOMPLETE,
            retryable=True,
        )
    choice = choices[0]
    message = choice.get("message")
    if choice.get("finish_reason") != "stop" or not isinstance(message, dict):
        raise DiagnosisProcessingError(
            DiagnosisErrorCode.MODEL_INCOMPLETE,
            retryable=True,
        )
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise DiagnosisProcessingError(
            DiagnosisErrorCode.MODEL_INCOMPLETE,
            retryable=True,
        )
    interaction_id = payload.get("id")
    model = payload.get("model")
    return (
        content,
        interaction_id if isinstance(interaction_id, str) and interaction_id else None,
        model if isinstance(model, str) and model else "unknown",
    )


def _model_label(model: str) -> str:
    label = f"openrouter:{model}"
    if len(label) > 128:
        raise DiagnosisProcessingError(
            DiagnosisErrorCode.MODEL_INVALID_RESPONSE,
            retryable=True,
        )
    return label
