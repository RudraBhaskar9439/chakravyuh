"""Interfaces implemented by infrastructure adapters in later phases."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from chakravyuh.domain.actions import ActionProposal, PolicyDecision
from chakravyuh.domain.events import NormalizedEvent
from chakravyuh.domain.incidents import Incident


class Clock(Protocol):
    def now(self) -> datetime: ...


class EventStore(Protocol):
    async def append(self, event: NormalizedEvent) -> bool:
        """Persist once and return False when the source event was already stored."""
        ...

    async def read_for_merchant(self, merchant_id: str) -> Sequence[NormalizedEvent]: ...


class IncidentRepository(Protocol):
    async def save(self, incident: Incident) -> None: ...

    async def get(self, incident_id: UUID) -> Incident | None: ...


class PolicyEngine(Protocol):
    async def evaluate(self, proposal: ActionProposal) -> PolicyDecision: ...


class GraphProjector(Protocol):
    async def project(self, event: NormalizedEvent) -> None: ...


class AuthoritativeStateReader(Protocol):
    async def fetch(self, provider_entity_id: str) -> NormalizedEvent: ...
