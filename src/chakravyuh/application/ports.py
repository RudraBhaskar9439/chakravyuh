"""Interfaces implemented by infrastructure adapters in later phases."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from chakravyuh.domain.actions import ActionProposal, PolicyDecision
from chakravyuh.domain.events import NormalizedEvent
from chakravyuh.domain.incidents import Incident
from chakravyuh.domain.webhooks import RawWebhookEvent

if TYPE_CHECKING:
    from chakravyuh.application.journey_reduction import JourneyReductionBatchResult
    from chakravyuh.application.normalization import NormalizationBatchResult
    from chakravyuh.domain.journeys import PaymentJourneyState
    from chakravyuh.domain.projections import (
        GraphProjectionInput,
        GraphProjectionReceipt,
        GraphRebuildCandidate,
        GraphRebuildReceipt,
        ProjectionLag,
        ProjectionWorkClaim,
    )


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


class WebhookNormalizer(Protocol):
    """Convert one verified provider event into the stable domain envelope."""

    version: str

    def normalize(self, event: RawWebhookEvent) -> NormalizedEvent: ...


class NormalizationWorkRepository(Protocol):
    """Atomically claim raw events and commit their normalization outcome."""

    async def process_batch(
        self,
        *,
        normalizer: WebhookNormalizer,
        worker_id: str,
        batch_size: int,
    ) -> NormalizationBatchResult: ...

    async def request_replay(
        self,
        event_id: UUID,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID: ...


class JourneyReducer(Protocol):
    """Pure, versioned reduction of one complete merchant correlation."""

    version: str

    def reduce(self, events: list[NormalizedEvent]) -> PaymentJourneyState: ...


class JourneyReductionRepository(Protocol):
    """Durably claim and materialize temporal payment journeys."""

    async def process_batch(
        self,
        *,
        reducer: JourneyReducer,
        worker_id: str,
        batch_size: int,
        max_events_per_journey: int,
    ) -> JourneyReductionBatchResult: ...

    async def request_replay(
        self,
        merchant_id: str,
        correlation_id: str,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID: ...

    async def get(
        self,
        merchant_id: str,
        correlation_id: str,
    ) -> PaymentJourneyState | None: ...


class DatabaseLifecycle(Protocol):
    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class IncidentRepository(Protocol):
    async def save(self, incident: Incident) -> None: ...

    async def get(self, incident_id: UUID) -> Incident | None: ...


class PolicyEngine(Protocol):
    async def evaluate(self, proposal: ActionProposal) -> PolicyDecision: ...


class GraphProjector(Protocol):
    async def initialize_schema(self) -> None: ...

    async def verify_connectivity(self) -> None: ...

    async def project(self, projection: GraphProjectionInput) -> GraphProjectionReceipt: ...

    async def prune_before(self, rebuild: GraphRebuildCandidate) -> GraphRebuildReceipt: ...

    async def close(self) -> None: ...


class GraphProjectionRepository(Protocol):
    async def claim_batch(
        self,
        *,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
    ) -> Sequence[ProjectionWorkClaim]: ...

    async def load(self, claim: ProjectionWorkClaim) -> GraphProjectionInput: ...

    async def complete(
        self,
        claim: ProjectionWorkClaim,
        receipt: GraphProjectionReceipt,
    ) -> None: ...

    async def fail(
        self,
        claim: ProjectionWorkClaim,
        *,
        error_code: str,
        max_failures: int,
        retry_delay_seconds: float,
    ) -> bool: ...

    async def lag(self) -> ProjectionLag: ...

    async def request_rebuild(
        self,
        *,
        requested_by: str,
        reason: str,
    ) -> tuple[UUID, int]: ...

    async def finalizable_rebuilds(self, *, limit: int) -> Sequence[GraphRebuildCandidate]: ...

    async def complete_rebuild(
        self,
        rebuild: GraphRebuildCandidate,
        receipt: GraphRebuildReceipt,
    ) -> bool: ...


class AuthoritativeStateReader(Protocol):
    async def fetch(self, provider_entity_id: str) -> NormalizedEvent: ...
