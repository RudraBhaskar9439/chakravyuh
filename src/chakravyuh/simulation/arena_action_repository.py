"""Deterministic in-memory action repository for the isolated Recovery Arena.

The repository mirrors the production Postgres state machine closely enough to exercise the
real control plane without letting benchmark writes touch operator or merchant data. Every state
transition is bound into a hash chain so an arena run cannot silently omit an approval, lease, or
mutation checkpoint.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from chakravyuh.domain.actions import (
    ActionApproval,
    ActionExecutionClaim,
    ActionExecutionResult,
    ActionProposal,
    ActionProposalSeed,
    ActionView,
    PolicyDecision,
)
from chakravyuh.domain.enums import (
    ActionApprovalDecision,
    ActionExecutionOperation,
    ActionExecutionStatus,
    PolicyOutcome,
)
from chakravyuh.domain.errors import ActionControlError, ActionControlErrorCode

_EMPTY_AUDIT_ROOT = hashlib.sha256(b"chakravyuh:recovery-arena:empty-audit").hexdigest()


def empty_control_audit_root() -> str:
    """Return the committed root used when a strategy correctly performs no control action."""

    return _EMPTY_AUDIT_ROOT


class ArenaControlAuditEvent(BaseModel):
    """One secret-free, tamper-evident control-plane transition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int = Field(ge=1)
    occurred_at: AwareDatetime
    principal_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=255)
    action: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=255)
    outcome: str = Field(min_length=1, max_length=64)
    details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_event_hash(self) -> ArenaControlAuditEvent:
        if _model_hash(self, exclude={"event_sha256"}) != self.event_sha256:
            msg = "arena control audit event hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ArenaRecoveryActionRepository:
    """Single-case repository enforcing policy, dual control, leases, and idempotency."""

    def __init__(
        self,
        seed: ActionProposalSeed,
        *,
        clock: Callable[[], datetime],
        uuid_factory: Callable[[], UUID],
    ) -> None:
        self._seed = seed
        self._clock = clock
        self._uuid_factory = uuid_factory
        self._view: ActionView | None = None
        self._idempotency_key: str | None = None
        self._current_claim: ActionExecutionClaim | None = None
        self._attempt_count = 0
        self._mutation_attempted = False
        self._audit_events: list[ArenaControlAuditEvent] = []

    @property
    def mutation_attempted(self) -> bool:
        return self._mutation_attempted

    @property
    def audit_events(self) -> tuple[ArenaControlAuditEvent, ...]:
        return tuple(self._audit_events)

    @property
    def audit_root_sha256(self) -> str:
        if not self._audit_events:
            return _EMPTY_AUDIT_ROOT
        return self._audit_events[-1].event_sha256

    async def load_seed(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> ActionProposalSeed | None:
        found = incident_id == self._seed.incident_id
        self._audit(
            principal_id,
            request_id,
            action="proposal_seed_load",
            resource_id=str(incident_id),
            outcome="success" if found else "not_found",
            details={"seed_found": found},
        )
        return self._seed if found else None

    async def create_proposal(
        self,
        proposal: ActionProposal,
        policy: PolicyDecision,
        *,
        principal_id: str,
        request_id: str,
    ) -> ActionView:
        if proposal.incident_id != self._seed.incident_id:
            raise ActionControlError(ActionControlErrorCode.NOT_FOUND)
        if self._view is not None:
            if proposal.idempotency_key != self._idempotency_key:
                raise ActionControlError(ActionControlErrorCode.STALE)
            self._audit(
                principal_id,
                request_id,
                action="proposal_reuse",
                resource_id=str(self._view.proposal.proposal_id),
                outcome="success",
                details={"idempotency_key": proposal.idempotency_key},
            )
            return self._view
        self._idempotency_key = proposal.idempotency_key
        self._view = ActionView(
            proposal=proposal,
            policy=policy,
            execution_status=ActionExecutionStatus.READY,
        )
        self._audit(
            principal_id,
            request_id,
            action="proposal_create",
            resource_id=str(proposal.proposal_id),
            outcome="success",
            details={
                "policy_input_hash": policy.input_hash,
                "policy_outcome": policy.outcome.value,
                "proposal_hash": proposal.proposal_hash,
            },
        )
        return self._view

    async def list_for_incident(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> Sequence[ActionView]:
        found = self._view is not None and incident_id == self._seed.incident_id
        self._audit(
            principal_id,
            request_id,
            action="proposal_history",
            resource_id=str(incident_id),
            outcome="success" if found else "not_found",
            details={"item_count": 1 if found else 0},
        )
        if not found:
            return ()
        assert self._view is not None
        return (self._view,)

    async def decide(
        self,
        proposal_id: UUID,
        *,
        principal_id: str,
        request_id: str,
        decision: ActionApprovalDecision,
        rationale: str,
    ) -> ActionView:
        view = self._require_view(proposal_id)
        if view.policy.outcome is not PolicyOutcome.REQUIRE_APPROVAL:
            raise ActionControlError(ActionControlErrorCode.POLICY_DENIED)
        if view.execution_status is not ActionExecutionStatus.READY:
            raise ActionControlError(ActionControlErrorCode.EXECUTION_TERMINAL)
        if view.proposal.proposed_by == principal_id:
            raise ActionControlError(ActionControlErrorCode.MAKER_CHECKER_VIOLATION)
        if view.proposal.expires_at <= self._now():
            raise ActionControlError(ActionControlErrorCode.EXPIRED)
        existing = next(
            (item for item in view.approvals if item.principal_id == principal_id),
            None,
        )
        if existing is not None and existing.decision is not decision:
            raise ActionControlError(ActionControlErrorCode.EXECUTION_TERMINAL)
        approvals = view.approvals
        if existing is None:
            approval = ActionApproval(
                approval_id=self._uuid_factory(),
                proposal_id=proposal_id,
                principal_id=principal_id,
                request_id=request_id,
                decision=decision,
                rationale=rationale,
                decided_at=self._now(),
            )
            approvals = (*approvals, approval)
            self._view = view.model_copy(update={"approvals": approvals})
        self._audit(
            principal_id,
            request_id,
            action="approval_decide",
            resource_id=str(proposal_id),
            outcome="success",
            details={"decision": decision.value, "rationale": rationale},
        )
        assert self._view is not None
        return self._view

    async def claim_execution(
        self,
        proposal_id: UUID,
        *,
        principal_id: str,
        request_id: str,
        lease_seconds: int,
    ) -> ActionExecutionClaim | ActionView:
        if not 5 <= lease_seconds <= 300:
            raise ValueError("execution lease is outside supported bounds")
        view = self._require_view(proposal_id)
        if view.execution_status is ActionExecutionStatus.SUCCEEDED:
            self._audit(
                principal_id,
                request_id,
                action="execution_idempotent",
                resource_id=str(proposal_id),
                outcome="success",
                details={},
            )
            return view
        self._validate_execution(view)
        now = self._now()
        if (
            view.execution_status is ActionExecutionStatus.PROCESSING
            and self._current_claim is not None
            and self._current_claim.lease_expires_at > now
        ):
            raise ActionControlError(ActionControlErrorCode.EXECUTION_IN_PROGRESS)
        operation = (
            ActionExecutionOperation.RECONCILE
            if self._mutation_attempted
            else ActionExecutionOperation.EXECUTE
        )
        self._attempt_count += 1
        claim = ActionExecutionClaim(
            execution_id=self._uuid_factory(),
            attempt_number=self._attempt_count,
            operation=operation,
            proposal=view.proposal,
            requested_by=principal_id,
            request_id=request_id,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
        self._current_claim = claim
        self._view = view.model_copy(update={"execution_status": ActionExecutionStatus.PROCESSING})
        self._audit(
            principal_id,
            request_id,
            action="execution_claim",
            resource_id=str(proposal_id),
            outcome="success",
            details={
                "attempt_number": claim.attempt_number,
                "operation": operation.value,
                "execution_id": str(claim.execution_id),
            },
        )
        return claim

    async def mark_mutation_started(self, claim: ActionExecutionClaim) -> None:
        self._validate_claim(claim)
        if claim.lease_expires_at <= self._now():
            raise ActionControlError(ActionControlErrorCode.LEASE_LOST)
        if not self._mutation_attempted:
            self._mutation_attempted = True
            self._audit(
                claim.requested_by,
                claim.request_id,
                action="mutation_checkpoint",
                resource_id=str(claim.proposal.proposal_id),
                outcome="authorized",
                details={"execution_id": str(claim.execution_id)},
            )

    async def complete_execution(
        self,
        claim: ActionExecutionClaim,
        result: ActionExecutionResult,
    ) -> ActionView:
        self._validate_claim(claim)
        assert self._view is not None
        self._view = self._view.model_copy(
            update={
                "execution_status": ActionExecutionStatus(result.outcome.value),
                "latest_result": result,
            }
        )
        self._current_claim = None
        self._audit(
            claim.requested_by,
            claim.request_id,
            action="execution_complete",
            resource_id=str(claim.proposal.proposal_id),
            outcome=result.outcome.value,
            details={
                "already_applied": result.already_applied,
                "error_code": result.error_code,
                "result_hash": result.result_hash,
            },
        )
        return self._view

    def _validate_execution(self, view: ActionView) -> None:
        if view.policy.outcome is PolicyOutcome.DENY:
            raise ActionControlError(ActionControlErrorCode.POLICY_DENIED)
        if any(item.decision is ActionApprovalDecision.REJECTED for item in view.approvals):
            raise ActionControlError(ActionControlErrorCode.REJECTED)
        if view.policy.outcome is PolicyOutcome.REQUIRE_APPROVAL and not any(
            item.decision is ActionApprovalDecision.APPROVED
            and item.principal_id != view.proposal.proposed_by
            for item in view.approvals
        ):
            raise ActionControlError(ActionControlErrorCode.APPROVAL_REQUIRED)
        if view.proposal.expires_at <= self._now():
            raise ActionControlError(ActionControlErrorCode.EXPIRED)
        if view.execution_status in {
            ActionExecutionStatus.BLOCKED,
            ActionExecutionStatus.UNCERTAIN,
        }:
            raise ActionControlError(ActionControlErrorCode.EXECUTION_TERMINAL)

    def _validate_claim(self, claim: ActionExecutionClaim) -> None:
        if (
            self._view is None
            or self._view.execution_status is not ActionExecutionStatus.PROCESSING
            or self._current_claim is None
            or self._current_claim.execution_id != claim.execution_id
            or claim.requested_by != self._current_claim.requested_by
        ):
            raise ActionControlError(ActionControlErrorCode.LEASE_LOST)

    def _require_view(self, proposal_id: UUID) -> ActionView:
        if self._view is None or self._view.proposal.proposal_id != proposal_id:
            raise ActionControlError(ActionControlErrorCode.NOT_FOUND)
        return self._view

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("arena action repository clock must be timezone-aware")
        return now

    def _audit(
        self,
        principal_id: str,
        request_id: str,
        *,
        action: str,
        resource_id: str,
        outcome: str,
        details: object,
    ) -> None:
        previous = self.audit_root_sha256
        draft = ArenaControlAuditEvent.model_construct(
            sequence=len(self._audit_events) + 1,
            occurred_at=self._now(),
            principal_id=principal_id,
            request_id=request_id,
            action=action,
            resource_id=resource_id,
            outcome=outcome,
            details_sha256=_canonical_hash(details),
            previous_event_sha256=previous,
            event_sha256="0" * 64,
        )
        event = ArenaControlAuditEvent.model_validate(
            {
                **draft.model_dump(mode="json"),
                "event_sha256": _model_hash(draft, exclude={"event_sha256"}),
            }
        )
        self._audit_events.append(event)


def _model_hash(model: BaseModel, *, exclude: set[str]) -> str:
    return _canonical_hash(model.model_dump(mode="json", exclude=exclude))


def _canonical_hash(value: object) -> str:
    body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()
