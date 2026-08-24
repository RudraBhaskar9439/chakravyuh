"""Application orchestration tests for temporal reduction."""

from unittest.mock import AsyncMock
from uuid import uuid4

from chakravyuh.application.invariant_evaluation import InvariantEvaluationBatchResult
from chakravyuh.application.journey_reduction import (
    JourneyReductionBatchResult,
    ProcessJourneyReductionBatch,
    RequestJourneyReductionReplay,
)
from chakravyuh.application.normalization import NormalizationBatchResult
from chakravyuh.application.pipeline import ProcessPipelineBatch
from chakravyuh.domain.journeys import TemporalPaymentJourneyReducer


async def test_process_reduction_batch_delegates_bounded_runtime_inputs() -> None:
    repository = AsyncMock()
    expected = JourneyReductionBatchResult(claimed=2, completed=1, dead_lettered=1)
    repository.process_batch.return_value = expected
    reducer = TemporalPaymentJourneyReducer()

    result = await ProcessJourneyReductionBatch(
        repository,
        reducer,
        worker_id="worker-1",
        batch_size=20,
        max_events_per_journey=1_000,
    ).execute()

    assert result is expected
    repository.process_batch.assert_awaited_once_with(
        reducer=reducer,
        worker_id="worker-1",
        batch_size=20,
        max_events_per_journey=1_000,
    )


async def test_reduction_replay_delegates_audited_operator_intent() -> None:
    repository = AsyncMock()
    replay_id = uuid4()
    repository.request_replay.return_value = replay_id

    result = await RequestJourneyReductionReplay(repository).execute(
        "merchant-1",
        "order-1",
        requested_by="operator@example.test",
        reason="Reducer v2 has been reviewed.",
    )

    assert result == replay_id
    repository.request_replay.assert_awaited_once_with(
        "merchant-1",
        "order-1",
        requested_by="operator@example.test",
        reason="Reducer v2 has been reviewed.",
    )


async def test_pipeline_runs_normalization_before_independent_reduction() -> None:
    calls: list[str] = []
    normalization = AsyncMock()
    reduction = AsyncMock()
    invariants = AsyncMock()

    async def normalize() -> NormalizationBatchResult:
        calls.append("normalization")
        return NormalizationBatchResult(claimed=3, completed=3)

    async def reduce() -> JourneyReductionBatchResult:
        calls.append("reduction")
        return JourneyReductionBatchResult(claimed=2, completed=1, dead_lettered=1)

    async def evaluate() -> InvariantEvaluationBatchResult:
        calls.append("invariants")
        return InvariantEvaluationBatchResult(claimed=4, completed=3, dead_lettered=1)

    normalization.execute.side_effect = normalize
    reduction.execute.side_effect = reduce
    invariants.execute.side_effect = evaluate

    result = await ProcessPipelineBatch(normalization, reduction, invariants).execute()

    assert calls == ["normalization", "reduction", "invariants"]
    assert result.claimed == 9
    assert result.completed == 7
    assert result.dead_lettered == 2
