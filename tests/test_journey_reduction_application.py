"""Application orchestration tests for temporal reduction."""

from unittest.mock import AsyncMock
from uuid import uuid4

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

    async def normalize() -> NormalizationBatchResult:
        calls.append("normalization")
        return NormalizationBatchResult(claimed=3, completed=3)

    async def reduce() -> JourneyReductionBatchResult:
        calls.append("reduction")
        return JourneyReductionBatchResult(claimed=2, completed=1, dead_lettered=1)

    normalization.execute.side_effect = normalize
    reduction.execute.side_effect = reduce

    result = await ProcessPipelineBatch(normalization, reduction).execute()

    assert calls == ["normalization", "reduction"]
    assert result.claimed == 5
    assert result.completed == 4
    assert result.dead_lettered == 1
