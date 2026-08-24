"""Use cases for durable temporal journey reduction and replay."""

from dataclasses import dataclass
from uuid import UUID

from chakravyuh.application.ports import JourneyReducer, JourneyReductionRepository


@dataclass(frozen=True, slots=True)
class JourneyReductionBatchResult:
    """Counts committed by one atomic temporal-reduction batch."""

    claimed: int = 0
    completed: int = 0
    dead_lettered: int = 0


class ProcessJourneyReductionBatch:
    """Run one bounded PostgreSQL-backed temporal-reduction batch."""

    def __init__(
        self,
        repository: JourneyReductionRepository,
        reducer: JourneyReducer,
        *,
        worker_id: str,
        batch_size: int,
        max_events_per_journey: int,
    ) -> None:
        self._repository = repository
        self._reducer = reducer
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._max_events_per_journey = max_events_per_journey

    async def execute(self) -> JourneyReductionBatchResult:
        return await self._repository.process_batch(
            reducer=self._reducer,
            worker_id=self._worker_id,
            batch_size=self._batch_size,
            max_events_per_journey=self._max_events_per_journey,
        )


class RequestJourneyReductionReplay:
    """Re-run a completed or dead-lettered journey with an immutable audit record."""

    def __init__(self, repository: JourneyReductionRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        merchant_id: str,
        correlation_id: str,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID:
        return await self._repository.request_replay(
            merchant_id,
            correlation_id,
            requested_by=requested_by,
            reason=reason,
        )
