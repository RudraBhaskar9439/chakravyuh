"""Diagnosis orchestration tests for retries, dead letters, and lease fencing."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from chakravyuh.application.diagnosis import (
    ProcessDiagnosisBatch,
    RequestDiagnosisReplay,
    _diagnosis_failure,
)
from chakravyuh.application.ports import DiagnosisRepository
from chakravyuh.domain.diagnoses import DiagnosisWorkClaim
from chakravyuh.domain.errors import (
    DiagnosisErrorCode,
    DiagnosisLeaseLostError,
    DiagnosisProcessingError,
)

NOW = datetime(2026, 8, 24, 17, tzinfo=UTC)


def _claim() -> DiagnosisWorkClaim:
    return DiagnosisWorkClaim(
        incident_id=uuid4(),
        source_revision_id=uuid4(),
        target_version=1,
        attempt_number=1,
        lease_owner="diagnosis:test:1",
        leased_until=NOW + timedelta(minutes=1),
    )


class _Repository:
    def __init__(self, claim: DiagnosisWorkClaim, *, lose_on: str | None = None) -> None:
        self.claim = claim
        self.lose_on = lose_on
        self.failure: Exception | None = None
        self.dead_letter = False
        self.completed: list[tuple[DiagnosisWorkClaim, Any]] = []
        self.failures: list[dict[str, object]] = []

    async def claim_batch(self, **parameters: object) -> list[DiagnosisWorkClaim]:
        del parameters
        return [self.claim]

    async def load(self, claim: DiagnosisWorkClaim) -> Any:
        assert claim is self.claim
        if self.failure is not None:
            raise self.failure
        return "seed"

    async def complete(self, claim: DiagnosisWorkClaim, receipt: Any) -> None:
        if self.lose_on == "complete":
            raise DiagnosisLeaseLostError()
        self.completed.append((claim, receipt))

    async def fail(self, claim: DiagnosisWorkClaim, **parameters: object) -> bool:
        assert claim is self.claim
        if self.lose_on == "fail":
            raise DiagnosisLeaseLostError()
        self.failures.append(parameters)
        return self.dead_letter

    async def request_replay(
        self,
        incident_id: UUID,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID:
        del incident_id, requested_by, reason
        return uuid4()


class _Assembler:
    def __init__(self) -> None:
        self.failure: Exception | None = None

    async def assemble(self, seed: Any) -> Any:
        assert seed == "seed"
        if self.failure is not None:
            raise self.failure
        return "evidence"


class _Diagnostician:
    async def diagnose(self, evidence: Any) -> Any:
        assert evidence == "evidence"
        return "receipt"

    async def close(self) -> None:
        return None


def _processor(
    repository: _Repository,
    assembler: _Assembler,
) -> ProcessDiagnosisBatch:
    return ProcessDiagnosisBatch(
        repository,
        assembler,
        _Diagnostician(),
        worker_id="diagnosis:test:1",
        batch_size=10,
        lease_seconds=60,
        max_failures=3,
        retry_delay_seconds=2,
    )


async def test_diagnosis_batch_completes_a_grounded_receipt() -> None:
    repository = _Repository(_claim())

    result = await _processor(repository, _Assembler()).execute()

    assert result.claimed == result.completed == 1
    assert repository.completed == [(repository.claim, "receipt")]
    assert repository.failures == []


@pytest.mark.parametrize("dead_letter", [False, True])
async def test_diagnosis_batch_preserves_stable_failure_and_retryability(
    dead_letter: bool,
) -> None:
    repository = _Repository(_claim())
    repository.dead_letter = dead_letter
    assembler = _Assembler()
    assembler.failure = DiagnosisProcessingError(
        DiagnosisErrorCode.EVIDENCE_TOO_LARGE,
        retryable=False,
    )

    result = await _processor(repository, assembler).execute()

    assert result.dead_lettered == int(dead_letter)
    assert result.retried == int(not dead_letter)
    assert repository.failures == [
        {
            "error_code": DiagnosisErrorCode.EVIDENCE_TOO_LARGE.value,
            "retryable": False,
            "max_failures": 3,
            "retry_delay_seconds": 2,
        }
    ]


async def test_diagnosis_batch_does_not_checkpoint_after_lease_loss() -> None:
    repository = _Repository(_claim())
    repository.failure = DiagnosisLeaseLostError()

    result = await _processor(repository, _Assembler()).execute()

    assert result.lease_lost == 1
    assert repository.completed == []
    assert repository.failures == []


@pytest.mark.parametrize("lose_on", ["complete", "fail"])
async def test_diagnosis_batch_reports_lease_loss_at_checkpoint(lose_on: str) -> None:
    repository = _Repository(_claim(), lose_on=lose_on)
    assembler = _Assembler()
    if lose_on == "fail":
        assembler.failure = RuntimeError("model boundary failed")

    result = await _processor(repository, assembler).execute()

    assert result.lease_lost == 1


def test_unknown_diagnosis_failures_are_payload_free_and_retryable() -> None:
    assert _diagnosis_failure(RuntimeError("sensitive detail")) == (
        DiagnosisErrorCode.INTERNAL.value,
        True,
    )


async def test_diagnosis_replay_forwards_bounded_operator_intent() -> None:
    incident_id = uuid4()
    replay_id = uuid4()

    class _ReplayRepository:
        async def request_replay(
            self,
            requested_incident_id: UUID,
            *,
            requested_by: str,
            reason: str,
        ) -> UUID:
            assert requested_incident_id == incident_id
            assert requested_by == "operator-1"
            assert reason == "Temporary model capacity recovered."
            return replay_id

    observed = await RequestDiagnosisReplay(cast(DiagnosisRepository, _ReplayRepository())).execute(
        incident_id,
        requested_by="operator-1",
        reason="Temporary model capacity recovered.",
    )

    assert observed == replay_id
