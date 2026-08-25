"""Leased orchestration for bounded, grounded incident diagnosis."""

from dataclasses import dataclass
from uuid import UUID

from chakravyuh.application.ports import (
    DiagnosisRepository,
    EvidenceAssembler,
    StructuredDiagnostician,
)
from chakravyuh.domain.errors import (
    DiagnosisErrorCode,
    DiagnosisLeaseLostError,
    DiagnosisProcessingError,
)


@dataclass(frozen=True, slots=True)
class DiagnosisBatchResult:
    claimed: int = 0
    completed: int = 0
    retried: int = 0
    dead_lettered: int = 0
    lease_lost: int = 0


class ProcessDiagnosisBatch:
    """Assemble, diagnose, and checkpoint only while the exact work lease is held."""

    def __init__(
        self,
        repository: DiagnosisRepository,
        assembler: EvidenceAssembler,
        diagnostician: StructuredDiagnostician,
        *,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
        max_failures: int,
        retry_delay_seconds: float,
    ) -> None:
        self._repository = repository
        self._assembler = assembler
        self._diagnostician = diagnostician
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._max_failures = max_failures
        self._retry_delay_seconds = retry_delay_seconds

    async def execute(self) -> DiagnosisBatchResult:
        claims = await self._repository.claim_batch(
            worker_id=self._worker_id,
            batch_size=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        completed = 0
        retried = 0
        dead_lettered = 0
        lease_lost = 0
        for claim in claims:
            try:
                seed = await self._repository.load(claim)
                evidence = await self._assembler.assemble(seed)
                receipt = await self._diagnostician.diagnose(evidence)
            except DiagnosisLeaseLostError:
                lease_lost += 1
                continue
            except Exception as failure:
                code, retryable = _diagnosis_failure(failure)
                try:
                    is_dead_letter = await self._repository.fail(
                        claim,
                        error_code=code,
                        retryable=retryable,
                        max_failures=self._max_failures,
                        retry_delay_seconds=self._retry_delay_seconds,
                    )
                except DiagnosisLeaseLostError:
                    lease_lost += 1
                    continue
                dead_lettered += int(is_dead_letter)
                retried += int(not is_dead_letter)
            else:
                try:
                    await self._repository.complete(claim, receipt)
                except DiagnosisLeaseLostError:
                    lease_lost += 1
                    continue
                completed += 1
        return DiagnosisBatchResult(
            claimed=len(claims),
            completed=completed,
            retried=retried,
            dead_lettered=dead_lettered,
            lease_lost=lease_lost,
        )


class RequestDiagnosisReplay:
    """Requeue one dead-lettered diagnosis with immutable operator intent."""

    def __init__(self, repository: DiagnosisRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        incident_id: UUID,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID:
        return await self._repository.request_replay(
            incident_id,
            requested_by=requested_by,
            reason=reason,
        )


def _diagnosis_failure(failure: Exception) -> tuple[str, bool]:
    """Map errors to payload-free audit codes and conservative retry behavior."""

    if isinstance(failure, DiagnosisProcessingError):
        return failure.code.value, failure.retryable
    return DiagnosisErrorCode.INTERNAL.value, True
