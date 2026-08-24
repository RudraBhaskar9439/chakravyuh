"""Recovery action, dual-control, and execution audit contracts."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from chakravyuh.domain.enums import (
    ActionApprovalDecision,
    ActionExecutionOperation,
    ActionExecutionOutcome,
    ActionExecutionStatus,
    ActionRisk,
    ActionType,
    IncidentStatus,
    IncidentType,
    PaymentStatus,
    PolicyOutcome,
)
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.money import Money


class ActionProposal(BaseModel):
    """A non-executable recovery proposal produced by deterministic or AI diagnosis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    source_revision_id: UUID
    diagnosis_id: UUID
    merchant_id: str = Field(min_length=1, max_length=255)
    incident_type: IncidentType
    action_type: ActionType
    risk: ActionRisk
    target: EntityReference
    amount: Money | None = None
    rationale: str = Field(min_length=1, max_length=2_000)
    evidence_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)
    idempotency_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposed_by: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=255)
    proposed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def expiry_and_hash_are_consistent(self) -> "ActionProposal":
        if self.expires_at <= self.proposed_at:
            msg = "action proposal expiry must follow creation"
            raise ValueError(msg)
        if _proposal_hash(self) != self.proposal_hash:
            msg = "action proposal hash does not match its canonical content"
            raise ValueError(msg)
        return self


class PolicyDecision(BaseModel):
    """Auditable result of deterministic policy evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    outcome: PolicyOutcome
    policy_version: str = Field(min_length=1, max_length=64)
    reasons: tuple[str, ...] = ()
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decided_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class ActionProposalSeed(BaseModel):
    """Exact immutable diagnosis and current-state checkpoint used to propose an action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: UUID
    source_revision_id: UUID
    diagnosis_id: UUID
    merchant_id: str = Field(min_length=1, max_length=255)
    incident_type: IncidentType
    incident_status: IncidentStatus
    target: EntityReference
    amount_at_risk: Money | None = None
    action_type: ActionType
    rationale: str = Field(min_length=1, max_length=2_000)
    evidence_ids: tuple[str, ...]
    confidence: float = Field(ge=0, le=1)


class ActionApproval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    principal_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=255)
    decision: ActionApprovalDecision
    rationale: str = Field(min_length=1, max_length=500)
    decided_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class ActionExecutionClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: UUID
    attempt_number: int = Field(ge=1)
    operation: ActionExecutionOperation
    proposal: ActionProposal
    requested_by: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=255)
    lease_expires_at: AwareDatetime


class ProviderPaymentState(BaseModel):
    """Allowlisted provider state; raw Razorpay responses never cross this boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    payment_id: str = Field(pattern=r"^pay_[A-Za-z0-9]+$", max_length=255)
    status: PaymentStatus
    amount: Money
    captured: bool
    order_id: str | None = Field(default=None, max_length=255)


class ActionExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: UUID
    proposal_id: UUID
    outcome: ActionExecutionOutcome
    error_code: str | None = Field(default=None, max_length=64)
    provider_state: ProviderPaymentState | None = None
    already_applied: bool = False
    completed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def outcome_and_hash_are_consistent(self) -> "ActionExecutionResult":
        if self.outcome is ActionExecutionOutcome.SUCCEEDED and self.provider_state is None:
            msg = "successful execution requires provider state"
            raise ValueError(msg)
        if self.outcome is not ActionExecutionOutcome.SUCCEEDED and self.error_code is None:
            msg = "unsuccessful execution requires an error code"
            raise ValueError(msg)
        if _result_hash(self) != self.result_hash:
            msg = "action result hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ActionView(BaseModel):
    """Operator-safe derived action state with immutable decisions and receipts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal: ActionProposal
    policy: PolicyDecision
    approvals: tuple[ActionApproval, ...] = ()
    execution_status: ActionExecutionStatus | None = None
    latest_result: ActionExecutionResult | None = None
    stale: bool = False
    expired: bool = False


def action_risk(action_type: ActionType) -> ActionRisk:
    if action_type is ActionType.FETCH_AUTHORITATIVE_STATE:
        return ActionRisk.READ_ONLY
    if action_type is ActionType.CAPTURE_PAYMENT:
        return ActionRisk.MONEY_MOVEMENT
    return ActionRisk.REVERSIBLE


def create_action_proposal(
    *,
    incident_id: UUID,
    source_revision_id: UUID,
    diagnosis_id: UUID,
    merchant_id: str,
    incident_type: IncidentType,
    action_type: ActionType,
    risk: ActionRisk,
    target: EntityReference,
    amount: Money | None,
    rationale: str,
    evidence_ids: tuple[str, ...],
    confidence: float,
    idempotency_key: str,
    proposed_by: str,
    request_id: str,
    proposed_at: datetime,
    expires_at: datetime,
    proposal_id: UUID | None = None,
) -> ActionProposal:
    """Construct and validate a proposal with its canonical tamper-evident hash."""

    draft = ActionProposal.model_construct(
        proposal_id=proposal_id or uuid4(),
        incident_id=incident_id,
        source_revision_id=source_revision_id,
        diagnosis_id=diagnosis_id,
        merchant_id=merchant_id,
        incident_type=incident_type,
        action_type=action_type,
        risk=risk,
        target=target,
        amount=amount,
        rationale=rationale,
        evidence_ids=evidence_ids,
        confidence=confidence,
        idempotency_key=idempotency_key,
        proposal_hash="0" * 64,
        proposed_by=proposed_by,
        request_id=request_id,
        proposed_at=proposed_at,
        expires_at=expires_at,
    )
    return ActionProposal.model_validate(
        {**draft.model_dump(), "proposal_hash": build_proposal_hash(draft)}
    )


def build_proposal_hash(proposal: ActionProposal) -> str:
    return _proposal_hash(proposal)


def build_result_hash(result: ActionExecutionResult) -> str:
    return _result_hash(result)


def canonical_idempotency_key(seed: ActionProposalSeed) -> str:
    return _hash(
        {
            "action_type": seed.action_type.value,
            "amount": None if seed.amount_at_risk is None else seed.amount_at_risk.model_dump(),
            "diagnosis_id": str(seed.diagnosis_id),
            "incident_id": str(seed.incident_id),
            "source_revision_id": str(seed.source_revision_id),
            "target": seed.target.model_dump(mode="json"),
        }
    )


def _proposal_hash(proposal: ActionProposal) -> str:
    return _hash(proposal.model_dump(mode="json", exclude={"proposal_hash"}))


def _result_hash(result: ActionExecutionResult) -> str:
    return _hash(result.model_dump(mode="json", exclude={"result_hash"}))


def _hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()
