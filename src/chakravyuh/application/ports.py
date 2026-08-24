"""Interfaces implemented by infrastructure adapters in later phases."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from chakravyuh.domain.actions import ActionProposal, PolicyDecision
from chakravyuh.domain.events import NormalizedEvent
from chakravyuh.domain.incidents import Incident
from chakravyuh.domain.webhooks import RawWebhookEvent


class Clock(Protocol):
    def now(self) -> datetime: ...


class EventStore(Protocol):
    async def append(self, event: NormalizedEvent) -> bool:
        """Persist once and return False when the source event was already stored."""
        ...

    async def read_for_merchant(self, merchant_id: str) -> Sequence[NormalizedEvent]: ...


class WebhookEventStore(Protocol):
    async def append(self, event: RawWebhookEvent) -> bool:
        """Persist once and return False for an identical provider retry."""
        ...

    async def get(
        self,
        merchant_id: str,
        source_event_id: str,
    ) -> RawWebhookEvent | None: ...


class DatabaseLifecycle(Protocol):
    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class IncidentRepository(Protocol):
    async def save(self, incident: Incident) -> None: ...

    async def get(self, incident_id: UUID) -> Incident | None: ...


class PolicyEngine(Protocol):
    async def evaluate(self, proposal: ActionProposal) -> PolicyDecision: ...


class GraphProjector(Protocol):
    async def project(self, event: NormalizedEvent) -> None: ...


class AuthoritativeStateReader(Protocol):
    async def fetch(self, provider_entity_id: str) -> NormalizedEvent: ...
