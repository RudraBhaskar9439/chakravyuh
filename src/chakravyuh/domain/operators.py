"""Read-only operator contracts assembled from immutable audit records."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from chakravyuh.domain.diagnoses import GuardedDiagnosis
from chakravyuh.domain.enums import IncidentRevisionReason, IncidentStatus, IncidentType
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.evidence import EvidenceSubgraph
from chakravyuh.domain.incidents import IncidentLifecycle
from chakravyuh.domain.money import Money


class IncidentSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: UUID
    merchant_id: str = Field(min_length=1, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=255)
    incident_type: IncidentType
    status: IncidentStatus
    affected_entity: EntityReference
    amount_at_risk: Money | None = None
    occurrence_count: int = Field(ge=1)
    first_detected_at: AwareDatetime
    last_detected_at: AwareDatetime
    revision_count: int = Field(ge=1)
    diagnosis_disposition: str | None = None
    diagnosis_confidence: float | None = Field(default=None, ge=0, le=1)
    latest_diagnosed_at: AwareDatetime | None = None


class IncidentPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[IncidentSummary, ...]
    next_cursor: str | None = None


class IncidentOverview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status_counts: dict[IncidentStatus, int]
    total_at_risk_subunits: dict[str, int]
    awaiting_diagnosis_count: int = Field(ge=0)
    diagnosis_dead_letter_count: int = Field(ge=0)


class IncidentRevisionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    revision_id: UUID
    evaluation_id: UUID
    state_generation: int = Field(ge=1)
    reason: IncidentRevisionReason
    status: IncidentStatus
    finding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    recorded_at: AwareDatetime


class DiagnosisRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    diagnosis_id: UUID
    source_revision_id: UUID
    target_version: int = Field(ge=1)
    model: str = Field(min_length=1, max_length=128)
    provider_interaction_id: str | None = Field(default=None, max_length=255)
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_subgraph: EvidenceSubgraph
    diagnosis: GuardedDiagnosis
    diagnosed_at: AwareDatetime
    recorded_at: AwareDatetime


class IncidentDetail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    incident: IncidentLifecycle
    revisions: tuple[IncidentRevisionRecord, ...]
    latest_diagnosis: DiagnosisRecord | None = None
