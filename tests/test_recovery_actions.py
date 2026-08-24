"""Recovery orchestration proofs for exact amounts, idempotency, and ambiguous outcomes."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from chakravyuh.application.recovery_actions import RecoveryActionControlPlane
from chakravyuh.domain.action_policy import DeterministicRecoveryPolicy, RecoveryPolicyConfig
from chakravyuh.domain.actions import (
    ActionExecutionClaim,
    ActionExecutionResult,
    ActionProposal,
    ActionProposalSeed,
    ActionView,
    PolicyDecision,
    ProviderPaymentState,
)
from chakravyuh.domain.enums import (
    ActionApprovalDecision,
    ActionExecutionOperation,
    ActionExecutionStatus,
    ActionRisk,
    ActionType,
    EntityType,
    IncidentStatus,
    IncidentType,
    PaymentStatus,
)
from chakravyuh.domain.errors import ActionControlErrorCode, RazorpayActionError
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.money import Money


def _seed(action_type: ActionType = ActionType.CAPTURE_PAYMENT) -> ActionProposalSeed:
    return ActionProposalSeed(
        incident_id=uuid4(),
        source_revision_id=uuid4(),
        diagnosis_id=uuid4(),
        merchant_id="merchant-test",
        incident_type=IncidentType.AUTHORIZED_NOT_CAPTURED,
        incident_status=IncidentStatus.DETECTED,
        target=EntityReference(entity_type=EntityType.PAYMENT, entity_id="pay_123"),
        amount_at_risk=Money(amount_subunits=10_000, currency="INR"),
        action_type=action_type,
        rationale="The authorization is still open.",
        evidence_ids=("invariant:authorization-open",),
        confidence=0.97,
    )


def _state(status: PaymentStatus, *, captured: bool) -> ProviderPaymentState:
    return ProviderPaymentState(
        payment_id="pay_123",
        status=status,
        amount=Money(amount_subunits=10_000, currency="INR"),
        captured=captured,
        order_id="order_123",
    )


class _Repository:
    def __init__(self, seed: ActionProposalSeed) -> None:
        self.seed = seed
        self.view: ActionView | None = None
        self.claim: ActionExecutionClaim | ActionView | None = None
        self.mutation_starts = 0
        self.results: list[ActionExecutionResult] = []

    async def load_seed(self, incident_id: UUID, **_: Any) -> ActionProposalSeed | None:
        return self.seed if incident_id == self.seed.incident_id else None

    async def create_proposal(
        self,
        proposal: ActionProposal,
        policy: PolicyDecision,
        **_: Any,
    ) -> ActionView:
        self.view = ActionView(
            proposal=proposal,
            policy=policy,
            execution_status=ActionExecutionStatus.READY,
        )
        return self.view

    async def list_for_incident(self, incident_id: UUID, **_: Any) -> tuple[ActionView, ...]:
        return () if self.view is None or incident_id != self.seed.incident_id else (self.view,)

    async def decide(
        self,
        proposal_id: UUID,
        *,
        decision: ActionApprovalDecision,
        **_: Any,
    ) -> ActionView:
        del proposal_id, decision
        assert self.view is not None
        return self.view

    async def claim_execution(
        self, proposal_id: UUID, **_: Any
    ) -> ActionExecutionClaim | ActionView:
        del proposal_id
        assert self.claim is not None
        return self.claim

    async def mark_mutation_started(self, claim: ActionExecutionClaim) -> None:
        del claim
        self.mutation_starts += 1

    async def complete_execution(
        self,
        claim: ActionExecutionClaim,
        result: ActionExecutionResult,
    ) -> ActionView:
        self.results.append(result)
        assert self.view is not None
        self.view = self.view.model_copy(
            update={
                "execution_status": ActionExecutionStatus(result.outcome.value),
                "latest_result": result,
            }
        )
        return self.view


class _Gateway:
    def __init__(self, *fetches: ProviderPaymentState | RazorpayActionError) -> None:
        self.fetches = list(fetches)
        self.capture_result: ProviderPaymentState | RazorpayActionError = _state(
            PaymentStatus.CAPTURED,
            captured=True,
        )
        self.fetch_calls = 0
        self.capture_calls = 0

    async def fetch_payment(self, payment_id: str) -> ProviderPaymentState:
        assert payment_id == "pay_123"
        self.fetch_calls += 1
        result = self.fetches.pop(0)
        if isinstance(result, RazorpayActionError):
            raise result
        return result

    async def capture_payment(self, payment_id: str, amount: Money) -> ProviderPaymentState:
        assert payment_id == "pay_123"
        assert amount == Money(amount_subunits=10_000, currency="INR")
        self.capture_calls += 1
        if isinstance(self.capture_result, RazorpayActionError):
            raise self.capture_result
        return self.capture_result

    async def close(self) -> None:
        return None


def _control(
    repository: _Repository,
    gateway: _Gateway,
) -> RecoveryActionControlPlane:
    return RecoveryActionControlPlane(
        repository,
        DeterministicRecoveryPolicy(
            RecoveryPolicyConfig(
                actions_enabled=True,
                test_credentials=True,
                merchant_id="merchant-test",
                maximum_capture_subunits=20_000,
                minimum_capture_confidence=0.9,
            )
        ),
        gateway,
        proposal_ttl_seconds=900,
        execution_lease_seconds=30,
    )


async def _propose_and_claim(
    repository: _Repository,
    gateway: _Gateway,
    *,
    operation: ActionExecutionOperation = ActionExecutionOperation.EXECUTE,
) -> tuple[RecoveryActionControlPlane, ActionProposal]:
    control = _control(repository, gateway)
    view = await control.propose(
        repository.seed.incident_id,
        principal_id="maker",
        request_id="proposal-request",
    )
    repository.claim = ActionExecutionClaim(
        execution_id=uuid4(),
        attempt_number=1,
        operation=operation,
        proposal=view.proposal,
        requested_by="checker",
        request_id="execution-request",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    return control, view.proposal


async def test_proposal_is_server_derived_and_idempotency_is_stable() -> None:
    repository = _Repository(_seed())
    control = _control(repository, _Gateway(_state(PaymentStatus.AUTHORIZED, captured=False)))

    first = await control.propose(
        repository.seed.incident_id,
        principal_id="maker",
        request_id="request-1",
    )
    second = await control.propose(
        repository.seed.incident_id,
        principal_id="maker",
        request_id="request-2",
    )

    assert first.proposal.amount == repository.seed.amount_at_risk
    assert first.proposal.risk is ActionRisk.MONEY_MOVEMENT
    assert first.proposal.evidence_ids == repository.seed.evidence_ids
    assert first.proposal.idempotency_key == second.proposal.idempotency_key


async def test_read_only_fetch_never_carries_or_moves_money() -> None:
    repository = _Repository(_seed(ActionType.FETCH_AUTHORITATIVE_STATE))
    gateway = _Gateway(_state(PaymentStatus.AUTHORIZED, captured=False))
    control, proposal = await _propose_and_claim(repository, gateway)

    view = await control.execute(
        proposal.proposal_id,
        principal_id="maker",
        request_id="execute-fetch",
    )

    assert proposal.amount is None
    assert proposal.risk is ActionRisk.READ_ONLY
    assert view.execution_status is ActionExecutionStatus.SUCCEEDED
    assert gateway.capture_calls == repository.mutation_starts == 0


async def test_capture_checkpoints_mutation_and_returns_exact_provider_receipt() -> None:
    repository = _Repository(_seed())
    gateway = _Gateway(_state(PaymentStatus.AUTHORIZED, captured=False))
    control, proposal = await _propose_and_claim(repository, gateway)

    view = await control.execute(
        proposal.proposal_id,
        principal_id="checker",
        request_id="execute-capture",
    )

    assert repository.mutation_starts == 1
    assert gateway.capture_calls == 1
    assert view.execution_status is ActionExecutionStatus.SUCCEEDED
    assert view.latest_result is not None
    assert not view.latest_result.already_applied


async def test_already_captured_preflight_is_idempotent_without_post() -> None:
    repository = _Repository(_seed())
    gateway = _Gateway(_state(PaymentStatus.CAPTURED, captured=True))
    control, proposal = await _propose_and_claim(repository, gateway)

    view = await control.execute(
        proposal.proposal_id,
        principal_id="checker",
        request_id="execute-existing",
    )

    assert gateway.capture_calls == repository.mutation_starts == 0
    assert view.latest_result is not None and view.latest_result.already_applied


async def test_capture_timeout_reconciles_by_fetch_without_blind_retry() -> None:
    repository = _Repository(_seed())
    gateway = _Gateway(
        _state(PaymentStatus.AUTHORIZED, captured=False),
        _state(PaymentStatus.CAPTURED, captured=True),
    )
    gateway.capture_result = RazorpayActionError(
        ActionControlErrorCode.PROVIDER_UNAVAILABLE,
        retryable=True,
    )
    control, proposal = await _propose_and_claim(repository, gateway)

    view = await control.execute(
        proposal.proposal_id,
        principal_id="checker",
        request_id="execute-timeout",
    )

    assert gateway.capture_calls == 1
    assert gateway.fetch_calls == 2
    assert view.execution_status is ActionExecutionStatus.SUCCEEDED
    assert view.latest_result is not None and view.latest_result.already_applied


async def test_ambiguous_capture_is_terminal_uncertain_and_reconcile_only() -> None:
    repository = _Repository(_seed())
    gateway = _Gateway(
        _state(PaymentStatus.AUTHORIZED, captured=False),
        _state(PaymentStatus.AUTHORIZED, captured=False),
    )
    gateway.capture_result = RazorpayActionError(
        ActionControlErrorCode.PROVIDER_UNAVAILABLE,
        retryable=True,
    )
    control, proposal = await _propose_and_claim(repository, gateway)

    view = await control.execute(
        proposal.proposal_id,
        principal_id="checker",
        request_id="execute-ambiguous",
    )

    assert view.execution_status is ActionExecutionStatus.UNCERTAIN
    assert gateway.capture_calls == 1
    assert view.latest_result is not None
    assert view.latest_result.error_code == ActionControlErrorCode.AUTHORITATIVE_STATE_CHANGED


async def test_crash_recovery_claim_only_reconciles_and_never_posts_again() -> None:
    repository = _Repository(_seed())
    gateway = _Gateway(_state(PaymentStatus.CAPTURED, captured=True))
    control, proposal = await _propose_and_claim(
        repository,
        gateway,
        operation=ActionExecutionOperation.RECONCILE,
    )

    view = await control.execute(
        proposal.proposal_id,
        principal_id="checker",
        request_id="reconcile-crash",
    )

    assert view.execution_status is ActionExecutionStatus.SUCCEEDED
    assert gateway.fetch_calls == 1
    assert gateway.capture_calls == repository.mutation_starts == 0
