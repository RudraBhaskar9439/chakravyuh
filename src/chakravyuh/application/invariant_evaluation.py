"""Use case for durable deterministic invariant evaluation."""

from dataclasses import dataclass

from chakravyuh.application.ports import InvariantEvaluationRepository, InvariantEvaluator


@dataclass(frozen=True, slots=True)
class InvariantEvaluationBatchResult:
    claimed: int = 0
    completed: int = 0
    dead_lettered: int = 0
    incidents_detected: int = 0
    incidents_updated: int = 0
    incidents_resolved: int = 0
    incidents_reopened: int = 0


class ProcessInvariantEvaluationBatch:
    """Run one bounded PostgreSQL-backed invariant batch."""

    def __init__(
        self,
        repository: InvariantEvaluationRepository,
        evaluator: InvariantEvaluator,
        *,
        worker_id: str,
        batch_size: int,
        max_events_per_journey: int,
    ) -> None:
        self._repository = repository
        self._evaluator = evaluator
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._max_events_per_journey = max_events_per_journey

    async def execute(self) -> InvariantEvaluationBatchResult:
        return await self._repository.process_batch(
            evaluator=self._evaluator,
            worker_id=self._worker_id,
            batch_size=self._batch_size,
            max_events_per_journey=self._max_events_per_journey,
        )
