"""Application-layer normalization orchestration tests."""

from uuid import UUID, uuid4

from chakravyuh.application.normalization import (
    NormalizationBatchResult,
    ProcessNormalizationBatch,
    RequestNormalizationReplay,
)
from chakravyuh.application.ports import WebhookNormalizer
from chakravyuh.domain.events import NormalizedEvent
from chakravyuh.domain.webhooks import RawWebhookEvent


class RecordingRepository:
    def __init__(self) -> None:
        self.process_call: tuple[WebhookNormalizer, str, int] | None = None
        self.replay_call: tuple[UUID, str, str] | None = None
        self.replay_id = uuid4()

    async def process_batch(
        self,
        *,
        normalizer: WebhookNormalizer,
        worker_id: str,
        batch_size: int,
    ) -> NormalizationBatchResult:
        self.process_call = (normalizer, worker_id, batch_size)
        return NormalizationBatchResult(claimed=3, completed=2, dead_lettered=1)

    async def request_replay(
        self,
        event_id: UUID,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID:
        self.replay_call = (event_id, requested_by, reason)
        return self.replay_id


class StubNormalizer:
    version = "stub-v1"

    def normalize(self, event: RawWebhookEvent) -> NormalizedEvent:
        raise NotImplementedError


async def test_process_batch_passes_explicit_worker_bounds() -> None:
    repository = RecordingRepository()
    normalizer = StubNormalizer()
    use_case = ProcessNormalizationBatch(
        repository,
        normalizer,
        worker_id="worker-1",
        batch_size=25,
    )

    result = await use_case.execute()

    assert result == NormalizationBatchResult(claimed=3, completed=2, dead_lettered=1)
    assert repository.process_call == (normalizer, "worker-1", 25)


async def test_replay_passes_operator_identity_and_reason() -> None:
    repository = RecordingRepository()
    event_id = uuid4()

    replay_id = await RequestNormalizationReplay(repository).execute(
        event_id,
        requested_by="operator-1",
        reason="Provider contract support was deployed.",
    )

    assert replay_id == repository.replay_id
    assert repository.replay_call == (
        event_id,
        "operator-1",
        "Provider contract support was deployed.",
    )
