"""Use cases for durable webhook normalization and controlled replay."""

from dataclasses import dataclass
from uuid import UUID

from chakravyuh.application.ports import NormalizationWorkRepository, WebhookNormalizer


@dataclass(frozen=True, slots=True)
class NormalizationBatchResult:
    """Counts committed by one atomic worker batch."""

    claimed: int = 0
    completed: int = 0
    dead_lettered: int = 0


class ProcessNormalizationBatch:
    """Run one bounded database-backed normalization batch."""

    def __init__(
        self,
        repository: NormalizationWorkRepository,
        normalizer: WebhookNormalizer,
        *,
        worker_id: str,
        batch_size: int,
    ) -> None:
        self._repository = repository
        self._normalizer = normalizer
        self._worker_id = worker_id
        self._batch_size = batch_size

    async def execute(self) -> NormalizationBatchResult:
        return await self._repository.process_batch(
            normalizer=self._normalizer,
            worker_id=self._worker_id,
            batch_size=self._batch_size,
        )


class RequestNormalizationReplay:
    """Return one dead-lettered event to the queue and retain operator intent."""

    def __init__(self, repository: NormalizationWorkRepository) -> None:
        self._repository = repository

    async def execute(self, event_id: UUID, *, requested_by: str, reason: str) -> UUID:
        return await self._repository.request_replay(
            event_id,
            requested_by=requested_by,
            reason=reason,
        )
