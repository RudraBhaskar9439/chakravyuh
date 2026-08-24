"""Provider-neutral contracts for the rebuildable graph projection."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from chakravyuh.domain.events import NormalizedEvent
from chakravyuh.domain.journeys import PaymentJourneyState, journey_state_hash


class GraphProjectionInput(BaseModel):
    """One authoritative PostgreSQL snapshot plus its immutable event evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state_generation: int = Field(ge=1)
    projection_epoch: AwareDatetime
    state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: PaymentJourneyState
    events: tuple[NormalizedEvent, ...]

    @model_validator(mode="after")
    def authoritative_evidence_is_consistent(self) -> "GraphProjectionInput":
        if journey_state_hash(self.state) != self.state_hash:
            msg = "projection state hash does not match its authoritative state"
            raise ValueError(msg)
        if len(self.events) != self.state.event_count:
            msg = "projection event evidence count does not match its state"
            raise ValueError(msg)
        identities = {event.event_id for event in self.events}
        if len(identities) != len(self.events):
            msg = "projection event evidence contains duplicate identities"
            raise ValueError(msg)
        if any(
            event.merchant_id != self.state.merchant_id
            or event.correlation_id != self.state.correlation_id
            for event in self.events
        ):
            msg = "projection event evidence belongs to a different journey"
            raise ValueError(msg)
        return self


class ProjectionWorkClaim(BaseModel):
    """A time-bounded right to project one merchant correlation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=255)
    target_version: int = Field(ge=1)
    state_generation: int = Field(ge=1)
    projection_epoch: AwareDatetime
    attempt_number: int = Field(ge=1)
    lease_owner: str = Field(min_length=1, max_length=255)
    leased_until: AwareDatetime


class ProjectionLag(BaseModel):
    """Payload-free projection health safe for readiness reporting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pending_count: int = Field(ge=0)
    processing_count: int = Field(ge=0)
    dead_letter_count: int = Field(ge=0)
    pending_rebuild_count: int = Field(ge=0)
    max_version_lag: int = Field(ge=0)
    oldest_unprojected_at: AwareDatetime | None = None
    oldest_unprojected_age_seconds: float = Field(ge=0)


class GraphProjectionHealth(BaseModel):
    """Combined database lag and Neo4j connectivity outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    healthy: bool
    neo4j_reachable: bool
    lag: ProjectionLag
    lag_threshold_seconds: float = Field(gt=0)
    checked_at: AwareDatetime
    reason: str | None = Field(default=None, max_length=64)


class GraphProjectionReceipt(BaseModel):
    """Idempotent graph write receipt used for checkpoint evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    merchant_id: str
    correlation_id: str
    state_generation: int = Field(ge=1)
    projection_epoch: AwareDatetime
    state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entity_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    projected_at: AwareDatetime
    projection_id: UUID


class GraphRebuildCandidate(BaseModel):
    """An audited rebuild whose epoch is fully projected and safe to prune."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rebuild_id: UUID
    projection_epoch: AwareDatetime


class GraphRebuildReceipt(BaseModel):
    """Aggregate, payload-free proof of an idempotent stale-node sweep."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rebuild_id: UUID
    projection_epoch: AwareDatetime
    journey_count_removed: int = Field(ge=0)
    entity_count_removed: int = Field(ge=0)
    event_count_removed: int = Field(ge=0)
    merchant_count_removed: int = Field(ge=0)
    pruned_at: AwareDatetime
