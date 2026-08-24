"""Incident and evidence contracts."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from chakravyuh.domain.enums import IncidentStatus, IncidentType
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.money import Money


class IncidentEvidence(BaseModel):
    """One verifiable fact supporting or contradicting an incident hypothesis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=1_000)
    entity: EntityReference
    event_id: UUID | None = None
    supports_hypothesis: bool = True


class Incident(BaseModel):
    """A detected broken money path awaiting diagnosis or recovery."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: UUID = Field(default_factory=uuid4)
    merchant_id: str = Field(min_length=1, max_length=255)
    incident_type: IncidentType
    status: IncidentStatus = IncidentStatus.DETECTED
    affected_entity: EntityReference
    amount_at_risk: Money
    detected_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    evidence: tuple[IncidentEvidence, ...] = ()


class IncidentLifecycle(BaseModel):
    """Authoritative current incident state backed by immutable revisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: UUID
    incident_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    merchant_id: str = Field(min_length=1, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=255)
    incident_type: IncidentType
    status: IncidentStatus
    rule_id: str = Field(min_length=1, max_length=64)
    rule_version: str = Field(min_length=1, max_length=64)
    affected_entity: EntityReference
    amount_at_risk: Money | None = None
    evidence: tuple[IncidentEvidence, ...] = ()
    finding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_generation: int = Field(ge=1)
    occurrence_count: int = Field(ge=1)
    first_detected_at: AwareDatetime
    last_detected_at: AwareDatetime
    resolved_at: AwareDatetime | None = None
    last_evaluation_id: UUID
