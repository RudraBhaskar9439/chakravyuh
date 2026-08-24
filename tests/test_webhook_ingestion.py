"""Application use-case tests independent of HTTP and PostgreSQL."""

from datetime import UTC, datetime

from chakravyuh.application.webhook_ingestion import IngestVerifiedWebhook
from chakravyuh.domain.enums import EventSource
from chakravyuh.domain.webhooks import RawWebhookEvent


class MemoryWebhookStore:
    def __init__(self) -> None:
        self.event: RawWebhookEvent | None = None

    async def append(self, event: RawWebhookEvent) -> bool:
        if self.event is None:
            self.event = event
            return True
        return False

    async def get(self, merchant_id: str, source_event_id: str) -> RawWebhookEvent | None:
        return self.event


def _event() -> RawWebhookEvent:
    return RawWebhookEvent(
        merchant_id="merchant-1",
        source=EventSource.RAZORPAY_WEBHOOK,
        source_event_id="event-1",
        event_type="payment.captured",
        occurred_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        payload={"event": "payment.captured"},
        raw_body=b"{}",
    )


async def test_ingestion_returns_canonical_identity_for_retry() -> None:
    store = MemoryWebhookStore()
    ingestion = IngestVerifiedWebhook(store)
    first = await ingestion.execute(_event())
    retry = await ingestion.execute(_event())

    assert first.accepted is True
    assert retry.accepted is False
    assert retry.event_id == first.event_id
