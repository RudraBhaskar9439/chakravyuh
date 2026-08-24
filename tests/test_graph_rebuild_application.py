"""Application tests for rebuild finalization and duplicate completion safety."""

from datetime import UTC, datetime
from uuid import uuid4

from chakravyuh.application.graph_rebuild import FinalizeGraphRebuilds
from chakravyuh.domain.projections import GraphRebuildCandidate, GraphRebuildReceipt


class FinalizationRepository:
    def __init__(self, candidates: list[GraphRebuildCandidate]) -> None:
        self.candidates = candidates
        self.completed: list[GraphRebuildReceipt] = []

    async def finalizable_rebuilds(self, *, limit: int):  # type: ignore[no-untyped-def]
        assert limit == 10
        return self.candidates

    async def complete_rebuild(self, rebuild, receipt):  # type: ignore[no-untyped-def]
        assert rebuild.rebuild_id == receipt.rebuild_id
        self.completed.append(receipt)
        return len(self.completed) == 1


class FinalizationProjector:
    async def prune_before(self, rebuild):  # type: ignore[no-untyped-def]
        return GraphRebuildReceipt(
            rebuild_id=rebuild.rebuild_id,
            projection_epoch=rebuild.projection_epoch,
            journey_count_removed=1,
            entity_count_removed=2,
            event_count_removed=3,
            merchant_count_removed=1,
            pruned_at=datetime.now(UTC),
        )


async def test_finalizer_is_idle_or_checkpoints_each_candidate() -> None:
    candidate = GraphRebuildCandidate(
        rebuild_id=uuid4(),
        projection_epoch=datetime.now(UTC),
    )
    repository = FinalizationRepository([candidate, candidate])
    finalizer = FinalizeGraphRebuilds(
        repository,  # type: ignore[arg-type]
        FinalizationProjector(),  # type: ignore[arg-type]
    )

    result = await finalizer.execute()

    assert result.candidates == 2
    assert result.completed == 1
    repository.candidates = []
    assert (await finalizer.execute()).candidates == 0
