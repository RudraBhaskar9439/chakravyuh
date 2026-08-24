"""Use case for durably accepting an already-authenticated webhook."""

from dataclasses import dataclass
from uuid import UUID

from chakravyuh.application.ports import WebhookEventStore
from chakravyuh.domain.webhooks import RawWebhookEvent


@dataclass(frozen=True, slots=True)
class WebhookIngestionResult:
    """Stable result returned at the transport boundary."""

    event_id: UUID
    accepted: bool


class IngestVerifiedWebhook:
    """Commit a verified event before allowing the provider to stop retrying."""

    def __init__(self, store: WebhookEventStore) -> None:
        self._store = store

    async def execute(self, event: RawWebhookEvent) -> WebhookIngestionResult:
        accepted = await self._store.append(event)
        if accepted:
            return WebhookIngestionResult(event_id=event.event_id, accepted=True)

        existing = await self._store.get(event.merchant_id, event.source_event_id)
        if existing is None:  # pragma: no cover - defensive adapter contract guard
            msg = "event store reported a duplicate but could not read it"
            raise RuntimeError(msg)
        return WebhookIngestionResult(event_id=existing.event_id, accepted=False)
