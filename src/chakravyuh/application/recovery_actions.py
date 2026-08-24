"""Audited proposal, maker-checker, execution, and ambiguity reconciliation workflow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from chakravyuh.application.ports import (
    PolicyEngine,
    RazorpayPaymentGateway,
    RecoveryActionRepository,
)
from chakravyuh.domain.actions import (
    ActionExecutionClaim,
    ActionExecutionResult,
    ActionProposal,
    ActionView,
    ProviderPaymentState,
    action_risk,
    build_result_hash,
    canonical_idempotency_key,
    create_action_proposal,
)
from chakravyuh.domain.enums import (
    ActionApprovalDecision,
    ActionExecutionOperation,
    ActionExecutionOutcome,
    ActionType,
    PaymentStatus,
)
from chakravyuh.domain.errors import (
    ActionControlError,
    ActionControlErrorCode,
    RazorpayActionError,
)


class RecoveryActionControlPlane:
    """Keep model output non-executable and run only policy-authorized provider operations."""

    def __init__(
        self,
        repository: RecoveryActionRepository,
        policy: PolicyEngine,
        gateway: RazorpayPaymentGateway,
        *,
        proposal_ttl_seconds: int,
        execution_lease_seconds: int,
    ) -> None:
        if not 60 <= proposal_ttl_seconds <= 3_600:
            raise ValueError("proposal TTL is outside supported bounds")
        if not 5 <= execution_lease_seconds <= 300:
            raise ValueError("execution lease is outside supported bounds")
        self._repository = repository
        self._policy = policy
        self._gateway = gateway
        self._proposal_ttl_seconds = proposal_ttl_seconds
        self._execution_lease_seconds = execution_lease_seconds

    async def propose(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> ActionView:
        seed = await self._repository.load_seed(
            incident_id,
            principal_id=principal_id,
            request_id=request_id,
        )
        if seed is None:
            raise ActionControlError(ActionControlErrorCode.NOT_FOUND)
        now = datetime.now(UTC)
        amount = seed.amount_at_risk if seed.action_type is ActionType.CAPTURE_PAYMENT else None
        proposal = create_action_proposal(
            proposal_id=uuid4(),
            incident_id=seed.incident_id,
            source_revision_id=seed.source_revision_id,
            diagnosis_id=seed.diagnosis_id,
            merchant_id=seed.merchant_id,
            incident_type=seed.incident_type,
            action_type=seed.action_type,
            risk=action_risk(seed.action_type),
            target=seed.target,
            amount=amount,
            rationale=seed.rationale,
            evidence_ids=seed.evidence_ids,
            confidence=seed.confidence,
            idempotency_key=canonical_idempotency_key(seed),
            proposed_by=principal_id,
            request_id=request_id,
            proposed_at=now,
            expires_at=now + timedelta(seconds=self._proposal_ttl_seconds),
        )
        policy = self._policy.evaluate(proposal)
        return await self._repository.create_proposal(
            proposal,
            policy,
            principal_id=principal_id,
            request_id=request_id,
        )

    async def list_for_incident(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> tuple[ActionView, ...]:
        return tuple(
            await self._repository.list_for_incident(
                incident_id,
                principal_id=principal_id,
                request_id=request_id,
            )
        )

    async def decide(
        self,
        proposal_id: UUID,
        *,
        principal_id: str,
        request_id: str,
        decision: ActionApprovalDecision,
        rationale: str,
    ) -> ActionView:
        return await self._repository.decide(
            proposal_id,
            principal_id=principal_id,
            request_id=request_id,
            decision=decision,
            rationale=rationale,
        )

    async def execute(
        self,
        proposal_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> ActionView:
        claimed = await self._repository.claim_execution(
            proposal_id,
            principal_id=principal_id,
            request_id=request_id,
            lease_seconds=self._execution_lease_seconds,
        )
        if isinstance(claimed, ActionView):
            return claimed
        result = await self._run_claim(claimed)
        return await self._repository.complete_execution(claimed, result)

    async def _run_claim(self, claim: ActionExecutionClaim) -> ActionExecutionResult:
        proposal = claim.proposal
        if claim.operation is ActionExecutionOperation.RECONCILE:
            return await self._reconcile(claim)
        if proposal.action_type is ActionType.FETCH_AUTHORITATIVE_STATE:
            try:
                state = await self._gateway.fetch_payment(proposal.target.entity_id)
            except RazorpayActionError as failure:
                return _failure_result(
                    claim,
                    ActionExecutionOutcome.RETRYABLE
                    if failure.retryable
                    else ActionExecutionOutcome.BLOCKED,
                    failure.code,
                )
            return _success_result(claim, state, already_applied=False)
        if proposal.action_type is ActionType.CAPTURE_PAYMENT:
            return await self._capture(claim)
        return _failure_result(
            claim,
            ActionExecutionOutcome.BLOCKED,
            ActionControlErrorCode.POLICY_DENIED,
        )

    async def _capture(self, claim: ActionExecutionClaim) -> ActionExecutionResult:
        proposal = claim.proposal
        assert proposal.amount is not None
        try:
            current = await self._gateway.fetch_payment(proposal.target.entity_id)
        except RazorpayActionError as failure:
            return _failure_result(
                claim,
                ActionExecutionOutcome.RETRYABLE
                if failure.retryable
                else ActionExecutionOutcome.BLOCKED,
                failure.code,
            )
        mismatch = _capture_state_mismatch(proposal, current)
        if mismatch is not None:
            return _failure_result(claim, ActionExecutionOutcome.BLOCKED, mismatch, current)
        if current.status is PaymentStatus.CAPTURED and current.captured:
            return _success_result(claim, current, already_applied=True)
        if current.status is not PaymentStatus.AUTHORIZED or current.captured:
            return _failure_result(
                claim,
                ActionExecutionOutcome.BLOCKED,
                ActionControlErrorCode.AUTHORITATIVE_STATE_CHANGED,
                current,
            )

        await self._repository.mark_mutation_started(claim)
        try:
            captured = await self._gateway.capture_payment(
                proposal.target.entity_id,
                proposal.amount,
            )
        except RazorpayActionError as failure:
            if not failure.retryable:
                return _failure_result(
                    claim,
                    ActionExecutionOutcome.BLOCKED,
                    failure.code,
                )
            return await self._reconcile(claim)
        mismatch = _capture_state_mismatch(proposal, captured)
        if (
            mismatch is not None
            or captured.status is not PaymentStatus.CAPTURED
            or not captured.captured
        ):
            return _failure_result(
                claim,
                ActionExecutionOutcome.UNCERTAIN,
                mismatch or ActionControlErrorCode.PROVIDER_INVALID_RESPONSE,
                captured,
            )
        return _success_result(claim, captured, already_applied=False)

    async def _reconcile(self, claim: ActionExecutionClaim) -> ActionExecutionResult:
        proposal = claim.proposal
        try:
            current = await self._gateway.fetch_payment(proposal.target.entity_id)
        except RazorpayActionError:
            return _failure_result(
                claim,
                ActionExecutionOutcome.UNCERTAIN,
                ActionControlErrorCode.PROVIDER_UNAVAILABLE,
            )
        mismatch = _capture_state_mismatch(proposal, current)
        if mismatch is not None:
            return _failure_result(claim, ActionExecutionOutcome.BLOCKED, mismatch, current)
        if current.status is PaymentStatus.CAPTURED and current.captured:
            return _success_result(claim, current, already_applied=True)
        return _failure_result(
            claim,
            ActionExecutionOutcome.UNCERTAIN,
            ActionControlErrorCode.AUTHORITATIVE_STATE_CHANGED,
            current,
        )


def _capture_state_mismatch(
    proposal: ActionProposal,
    state: ProviderPaymentState,
) -> ActionControlErrorCode | None:
    if state.payment_id != proposal.target.entity_id or proposal.amount is None:
        return ActionControlErrorCode.PROVIDER_INVALID_RESPONSE
    if state.amount != proposal.amount:
        return ActionControlErrorCode.AUTHORITATIVE_STATE_CHANGED
    return None


def _success_result(
    claim: ActionExecutionClaim,
    state: ProviderPaymentState,
    *,
    already_applied: bool,
) -> ActionExecutionResult:
    draft = ActionExecutionResult.model_construct(
        execution_id=claim.execution_id,
        proposal_id=claim.proposal.proposal_id,
        outcome=ActionExecutionOutcome.SUCCEEDED,
        error_code=None,
        provider_state=state,
        already_applied=already_applied,
        completed_at=datetime.now(UTC),
        result_hash="0" * 64,
    )
    return ActionExecutionResult.model_validate(
        {**draft.model_dump(), "result_hash": build_result_hash(draft)}
    )


def _failure_result(
    claim: ActionExecutionClaim,
    outcome: ActionExecutionOutcome,
    code: ActionControlErrorCode,
    state: ProviderPaymentState | None = None,
) -> ActionExecutionResult:
    draft = ActionExecutionResult.model_construct(
        execution_id=claim.execution_id,
        proposal_id=claim.proposal.proposal_id,
        outcome=outcome,
        error_code=code.value,
        provider_state=state,
        already_applied=False,
        completed_at=datetime.now(UTC),
        result_hash="0" * 64,
    )
    return ActionExecutionResult.model_validate(
        {**draft.model_dump(), "result_hash": build_result_hash(draft)}
    )
