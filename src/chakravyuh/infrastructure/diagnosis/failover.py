"""Ordered, sanitized failover for structured diagnosis providers."""

from __future__ import annotations

from collections.abc import Sequence

import structlog

from chakravyuh.application.ports import StructuredDiagnostician
from chakravyuh.domain.diagnoses import DiagnosisReceipt
from chakravyuh.domain.errors import DiagnosisErrorCode, DiagnosisProcessingError
from chakravyuh.domain.evidence import EvidenceSubgraph

logger = structlog.get_logger(__name__)


class FailoverStructuredDiagnostician:
    """Try providers in fixed order and expose only stable failure metadata."""

    def __init__(self, providers: Sequence[StructuredDiagnostician]) -> None:
        if not providers:
            msg = "at least one diagnosis provider is required"
            raise ValueError(msg)
        self._providers = tuple(providers)

    @property
    def provider_order(self) -> tuple[str, ...]:
        return tuple(_provider_name(provider) for provider in self._providers)

    async def diagnose(self, evidence: EvidenceSubgraph) -> DiagnosisReceipt:
        last_failure: DiagnosisProcessingError | None = None
        for index, provider in enumerate(self._providers):
            try:
                return await provider.diagnose(evidence)
            except DiagnosisProcessingError as failure:
                last_failure = failure
                has_fallback = index + 1 < len(self._providers)
                if not failure.retryable or not has_fallback:
                    if len(self._providers) == 1 or not failure.retryable:
                        raise
                    break
                await logger.awarning(
                    "diagnosis_provider_fallback",
                    failed_provider=_provider_name(provider),
                    error_code=failure.code.value,
                    next_provider=_provider_name(self._providers[index + 1]),
                )
        raise DiagnosisProcessingError(
            DiagnosisErrorCode.MODEL_FAILOVER_EXHAUSTED,
            retryable=True,
        ) from last_failure

    async def close(self) -> None:
        first_failure: Exception | None = None
        for provider in self._providers:
            try:
                await provider.close()
            except Exception as failure:  # pragma: no cover - defensive shutdown path
                if first_failure is None:
                    first_failure = failure
        if first_failure is not None:
            raise first_failure


def _provider_name(provider: StructuredDiagnostician) -> str:
    name = getattr(provider, "provider", type(provider).__name__)
    return name if isinstance(name, str) and name else type(provider).__name__
