"""Recovery action and deterministic policy decision contracts."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from chakravyuh.domain.enums import ActionRisk, ActionType, PolicyOutcome
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.money import Money


class ActionProposal(BaseModel):
    """A non-executable recovery proposal produced by deterministic or AI diagnosis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    merchant_id: str = Field(min_length=1, max_length=255)
    action_type: ActionType
    risk: ActionRisk
    target: EntityReference
    amount: Money | None = None
    rationale: str = Field(min_length=1, max_length=2_000)
    evidence_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)
    idempotency_key: str = Field(min_length=1, max_length=255)
    proposed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class PolicyDecision(BaseModel):
    """Auditable result of deterministic policy evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    outcome: PolicyOutcome
    policy_version: str = Field(min_length=1, max_length=64)
    reasons: tuple[str, ...] = ()
    decided_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
