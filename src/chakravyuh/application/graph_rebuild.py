"""Finalize fully projected rebuild epochs by pruning older graph residue."""

from dataclasses import dataclass

from chakravyuh.application.ports import GraphProjectionRepository, GraphProjector


@dataclass(frozen=True, slots=True)
class GraphRebuildFinalizationResult:
    candidates: int = 0
    completed: int = 0


class FinalizeGraphRebuilds:
    """Idempotently sweep graph nodes older than completed rebuild epochs."""

    def __init__(
        self,
        repository: GraphProjectionRepository,
        projector: GraphProjector,
        *,
        batch_size: int = 10,
    ) -> None:
        self._repository = repository
        self._projector = projector
        self._batch_size = batch_size

    async def execute(self) -> GraphRebuildFinalizationResult:
        candidates = await self._repository.finalizable_rebuilds(limit=self._batch_size)
        completed = 0
        for rebuild in candidates:
            receipt = await self._projector.prune_before(rebuild)
            completed += int(await self._repository.complete_rebuild(rebuild, receipt))
        return GraphRebuildFinalizationResult(
            candidates=len(candidates),
            completed=completed,
        )
