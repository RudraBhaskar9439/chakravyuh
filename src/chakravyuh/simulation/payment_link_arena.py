"""Held-out Recovery Arena v2 for provider-confirmed failed-payment recovery.

Arena v1 remains immutable. This extension reuses its committed 10,005 observed
journeys while applying a separately sealed oracle and provider twin for the
``failed_without_recovery -> create_payment_link -> payment_link.paid`` path.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chakravyuh.application.ports import RazorpayPaymentGateway
from chakravyuh.application.recovery_actions import RecoveryActionControlPlane
from chakravyuh.domain.action_policy import DeterministicRecoveryPolicy, RecoveryPolicyConfig
from chakravyuh.domain.actions import (
    ActionProposalSeed,
    ActionView,
    ProviderPaymentLinkState,
    ProviderPaymentState,
)
from chakravyuh.domain.enums import (
    ActionApprovalDecision,
    ActionExecutionStatus,
    ActionType,
    EntityType,
    EventSource,
    IncidentStatus,
    IncidentType,
    PaymentStatus,
    PolicyOutcome,
)
from chakravyuh.domain.errors import ActionControlErrorCode, RazorpayActionError
from chakravyuh.domain.invariants import DeterministicPaymentInvariantEvaluator, InvariantFinding
from chakravyuh.domain.journeys import JourneyEntityState, reduce_payment_journey
from chakravyuh.domain.money import Money
from chakravyuh.domain.recovery_arena import ArenaDatasetRole, create_recovery_arena_contract
from chakravyuh.domain.webhooks import RawWebhookEvent
from chakravyuh.simulation.arena_action_repository import (
    ArenaRecoveryActionRepository,
    empty_control_audit_root,
)
from chakravyuh.simulation.recovery_portfolio import (
    ArenaEvaluationCase,
    ArenaObservedCase,
    RecoveryPortfolio,
    generate_recovery_portfolio,
)

ARENA_VERSION = "payment-link-recovery-arena-v2"
_MAXIMUM_LINK_SUBUNITS = 100_000
_MANUAL_REVIEW_COST_SUBUNITS = 2_000
_INCORRECT_ACTION_COST_SUBUNITS = 10_000
_LINK_TTL_SECONDS = 86_400
_MAKER = "payment-link-arena-maker"
_CHECKER = "payment-link-arena-checker"
_EXECUTOR = "payment-link-arena-executor"


class PaymentLinkStrategyName(StrEnum):
    NO_INTERVENTION = "no_intervention"
    LINK_EVERY_FAILED_PAYMENT = "link_every_failed_payment"
    CHAKRAVYUH = "chakravyuh"


class PaymentLinkFault(StrEnum):
    PAID = "paid"
    DUPLICATE_PAID_WEBHOOK = "duplicate_paid_webhook"
    PAID_WITH_LOST_CREATE_RESPONSE = "paid_with_lost_create_response"
    CREATED_NEVER_PAID = "created_never_paid"
    TIMEOUT_BEFORE_CREATE = "timeout_before_create"
    TIMEOUT_AFTER_CREATE = "timeout_after_create"
    EXPIRED_RESPONSE = "expired_response"
    CONFLICTING_AMOUNT_RESPONSE = "conflicting_amount_response"


class PaymentLinkArenaContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str = ARENA_VERSION
    base_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategies: tuple[PaymentLinkStrategyName, ...] = tuple(PaymentLinkStrategyName)
    held_out_case_count: int = 10_005
    recoverable_incident: IncidentType = IncidentType.FAILED_WITHOUT_RECOVERY
    executable_action: ActionType = ActionType.CREATE_PAYMENT_LINK
    confirmation_event: str = "payment_link.paid"
    maximum_link_subunits: int = _MAXIMUM_LINK_SUBUNITS
    link_ttl_seconds: int = _LINK_TTL_SECONDS
    manual_review_cost_subunits: int = _MANUAL_REVIEW_COST_SUBUNITS
    incorrect_action_cost_subunits: int = _INCORRECT_ACTION_COST_SUBUNITS
    fault_scenarios: tuple[PaymentLinkFault, ...] = tuple(PaymentLinkFault)
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_contract(self) -> PaymentLinkArenaContract:
        if self.strategies != tuple(PaymentLinkStrategyName):
            raise ValueError("payment-link arena requires all strategies in canonical order")
        if self.fault_scenarios != tuple(PaymentLinkFault):
            raise ValueError("payment-link arena requires all fault scenarios")
        if _model_hash(self, exclude={"contract_sha256"}) != self.contract_sha256:
            raise ValueError("payment-link arena contract hash mismatch")
        return self


class PaymentLinkCaseOracle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    expected_incident: bool
    action_eligible: bool
    recoverable: bool
    fault: PaymentLinkFault
    payment_id: str
    amount: Money
    oracle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_oracle(self) -> PaymentLinkCaseOracle:
        if self.action_eligible and not self.expected_incident:
            raise ValueError("eligible payment-link case requires the expected incident")
        if self.recoverable and not self.action_eligible:
            raise ValueError("recoverable payment-link case must be action eligible")
        if _model_hash(self, exclude={"oracle_sha256"}) != self.oracle_sha256:
            raise ValueError("payment-link oracle hash mismatch")
        return self


class PaymentLinkStrategyObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: PaymentLinkStrategyName
    case_id: str
    detected_expected_incident: bool = False
    proposal_created: bool = False
    policy_denied: bool = False
    checker_review_count: int = Field(default=0, ge=0, le=1)
    action_attempted: bool = False
    target_payment_id: str | None = None
    provider_returned_success: bool = False
    stable_error_code: str | None = None
    audit_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PaymentLinkCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    strategy: PaymentLinkStrategyName
    detection_true_positive: bool = False
    detection_false_positive: bool = False
    detection_false_negative: bool = False
    action_attempted: bool
    correct_action: bool
    incorrect_action: bool
    provider_returned_success: bool
    provider_confirmed: bool
    confirmed_recovery: bool
    recoverable_missed: bool
    provider_operation_count: int = Field(ge=0)
    applied_link_creation_count: int = Field(ge=0)
    duplicate_link_creation_count: int = Field(ge=0)
    confirmation_delivery_count: int = Field(ge=0)
    unique_confirmation_count: int = Field(ge=0)
    recovered_subunits: int = Field(ge=0)
    manual_review_cost_subunits: int = Field(ge=0)
    incorrect_action_cost_subunits: int = Field(ge=0)
    stable_error_code: str | None = None
    audit_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_result(self) -> PaymentLinkCaseResult:
        if self.confirmed_recovery and not self.provider_confirmed:
            raise ValueError("recovery credit requires provider confirmation")
        if self.unique_confirmation_count > self.confirmation_delivery_count:
            raise ValueError("unique confirmations cannot exceed deliveries")
        if _model_hash(self, exclude={"result_sha256"}) != self.result_sha256:
            raise ValueError("payment-link result hash mismatch")
        return self


class PaymentLinkStrategyMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: PaymentLinkStrategyName
    case_count: int
    expected_incident_count: int
    action_eligible_count: int
    oracle_recoverable_count: int
    action_attempt_count: int
    correct_action_count: int
    incorrect_action_count: int
    confirmed_recovery_count: int
    missed_recoverable_count: int
    duplicate_link_creation_count: int
    confirmation_delivery_count: int
    unique_confirmation_count: int
    detection_precision: float | None = Field(default=None, ge=0, le=1)
    detection_recall: float | None = Field(default=None, ge=0, le=1)
    action_precision: float | None = Field(default=None, ge=0, le=1)
    action_recall: float = Field(ge=0, le=1)
    recovered_subunits: int
    manual_review_cost_subunits: int
    incorrect_action_cost_subunits: int
    net_recovery_value_subunits: int
    results_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PaymentLinkArenaReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: str = ARENA_VERSION
    code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    contract: PaymentLinkArenaContract
    base_portfolio_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    oracle_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategies: tuple[PaymentLinkStrategyMetrics, ...]
    fault_counts: dict[str, int]
    claims_boundary: str
    passed: bool
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_report(self) -> PaymentLinkArenaReport:
        if tuple(item.strategy for item in self.strategies) != tuple(PaymentLinkStrategyName):
            raise ValueError("payment-link report strategy order mismatch")
        if self.passed != _report_passed(self.strategies):
            raise ValueError("payment-link report pass flag mismatch")
        if _model_hash(self, exclude={"report_sha256"}) != self.report_sha256:
            raise ValueError("payment-link report hash mismatch")
        return self


class _PaymentLinkTwin:
    """Deterministic narrow gateway with immutable secret-free operation evidence."""

    def __init__(self, case: ArenaEvaluationCase, oracle: PaymentLinkCaseOracle) -> None:
        self._payment = case.oracle.provider_plan.initial_state
        self._oracle = oracle
        self._link: ProviderPaymentLinkState | None = None
        self._operations: list[dict[str, object]] = []
        self._confirmations: list[RawWebhookEvent] = []
        self._creation_count = 0

    def gateway(self) -> RazorpayPaymentGateway:
        return self

    async def fetch_payment(self, payment_id: str) -> ProviderPaymentState:
        self._record("fetch_payment", payment_id, "returned")
        if payment_id != self._payment.payment_id:
            raise RazorpayActionError(
                ActionControlErrorCode.PROVIDER_INVALID_RESPONSE,
                retryable=False,
            )
        return self._payment

    async def capture_payment(self, payment_id: str, amount: Money) -> ProviderPaymentState:
        del payment_id, amount
        self._record("capture_payment", "forbidden", "rejected")
        raise RazorpayActionError(ActionControlErrorCode.POLICY_DENIED, retryable=False)

    async def create_payment_link(
        self,
        *,
        amount: Money,
        reference_id: str,
        description: str,
        expire_by: datetime,
    ) -> ProviderPaymentLinkState:
        del description, expire_by
        fault = self._oracle.fault
        if amount != self._payment.amount or not reference_id:
            self._record("create_payment_link", reference_id, "invalid")
            raise RazorpayActionError(
                ActionControlErrorCode.AUTHORITATIVE_STATE_CHANGED,
                retryable=False,
            )
        if fault is PaymentLinkFault.TIMEOUT_BEFORE_CREATE:
            self._record("create_payment_link", reference_id, "timeout_before_create")
            raise RazorpayActionError(
                ActionControlErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
            )
        if fault is PaymentLinkFault.CONFLICTING_AMOUNT_RESPONSE:
            self._creation_count += 1
            conflicting = Money(
                amount_subunits=amount.amount_subunits + 100,
                currency=amount.currency,
            )
            self._link = self._link_state(reference_id, conflicting, status="created")
            self._record("create_payment_link", reference_id, "conflicting_amount")
            return self._link
        if fault is PaymentLinkFault.EXPIRED_RESPONSE:
            self._creation_count += 1
            self._link = self._link_state(reference_id, amount, status="expired")
            self._record("create_payment_link", reference_id, "expired")
            return self._link

        self._creation_count += 1
        paid_on_reconcile = fault is PaymentLinkFault.PAID_WITH_LOST_CREATE_RESPONSE
        self._link = self._link_state(
            reference_id,
            amount,
            status="paid" if paid_on_reconcile else "created",
        )
        if fault in {
            PaymentLinkFault.PAID,
            PaymentLinkFault.DUPLICATE_PAID_WEBHOOK,
            PaymentLinkFault.PAID_WITH_LOST_CREATE_RESPONSE,
        }:
            self._enqueue_paid(
                duplicates=2 if fault is PaymentLinkFault.DUPLICATE_PAID_WEBHOOK else 1
            )
        if fault in {
            PaymentLinkFault.TIMEOUT_AFTER_CREATE,
            PaymentLinkFault.PAID_WITH_LOST_CREATE_RESPONSE,
        }:
            self._record("create_payment_link", reference_id, "timeout_after_create")
            raise RazorpayActionError(
                ActionControlErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
            )
        self._record("create_payment_link", reference_id, "returned")
        return self._link

    async def fetch_payment_link(self, *, reference_id: str) -> ProviderPaymentLinkState | None:
        outcome = "not_found" if self._link is None else "returned"
        self._record("fetch_payment_link", reference_id, outcome)
        if self._link is not None and self._link.reference_id != reference_id:
            return None
        return self._link

    async def close(self) -> None:
        return None

    def drain_confirmations(self) -> tuple[RawWebhookEvent, ...]:
        items = tuple(self._confirmations)
        self._confirmations.clear()
        return items

    def snapshot(self) -> tuple[int, int, str]:
        document = {
            "case_id": self._oracle.case_id,
            "creation_count": self._creation_count,
            "link": None if self._link is None else self._link.model_dump(mode="json"),
            "operations": self._operations,
        }
        return len(self._operations), self._creation_count, _canonical_hash(document)

    def _link_state(
        self, reference_id: str, amount: Money, *, status: str
    ) -> ProviderPaymentLinkState:
        identity = hashlib.sha256(f"{self._oracle.case_id}:{reference_id}".encode()).hexdigest()[
            :20
        ]
        paid = amount if status == "paid" else Money(amount_subunits=0, currency=amount.currency)
        return ProviderPaymentLinkState(
            payment_link_id=f"plink_{identity}",
            status=status,
            amount=amount,
            amount_paid=paid,
            short_url=f"https://rzp.io/i/{identity}",
            reference_id=reference_id,
        )

    def _enqueue_paid(self, *, duplicates: int) -> None:
        assert self._link is not None
        event_identity = f"plink_paid_{self._oracle.case_id[5:]}"
        payload = {
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {
                    "entity": self._link.model_dump(mode="json"),
                }
            },
        }
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        for _ in range(duplicates):
            self._confirmations.append(
                RawWebhookEvent(
                    event_id=uuid5(NAMESPACE_URL, f"{event_identity}:{len(self._confirmations)}"),
                    merchant_id="merchant_arena",
                    source=EventSource.RAZORPAY_WEBHOOK,
                    source_event_id=event_identity,
                    event_type="payment_link.paid",
                    occurred_at=self._payment_time,
                    observed_at=self._payment_time,
                    payload=payload,
                    raw_body=body,
                )
            )

    @property
    def _payment_time(self) -> datetime:
        return datetime.fromisoformat("2026-01-01T00:00:00+00:00")

    def _record(self, operation: str, target: str, outcome: str) -> None:
        self._operations.append(
            {
                "sequence": len(self._operations) + 1,
                "operation": operation,
                "target": target,
                "outcome": outcome,
            }
        )


class _CaseUuidFactory:
    def __init__(self, case_id: str) -> None:
        self._case_id = case_id
        self._sequence = 0

    def __call__(self) -> UUID:
        self._sequence += 1
        return uuid5(
            NAMESPACE_URL,
            f"chakravyuh:payment-link-arena:{self._case_id}:{self._sequence}",
        )


class _FixedClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def __call__(self) -> datetime:
        return self._value


def create_payment_link_arena_contract() -> PaymentLinkArenaContract:
    base = create_recovery_arena_contract()
    draft = PaymentLinkArenaContract.model_construct(
        base_contract_sha256=base.contract_sha256,
        contract_sha256="0" * 64,
    )
    return PaymentLinkArenaContract.model_validate(
        {
            **draft.model_dump(mode="json"),
            "contract_sha256": _model_hash(draft, exclude={"contract_sha256"}),
        }
    )


def generate_payment_link_arena_portfolio(*, seed_count: int = 667) -> RecoveryPortfolio:
    base = create_recovery_arena_contract()
    held_out = base.partition(ArenaDatasetRole.HELD_OUT)
    if not 1 <= seed_count <= held_out.seed_count:
        raise ValueError("payment-link arena seed count must stay inside held-out partition")
    return generate_recovery_portfolio(
        base,
        dataset_role=ArenaDatasetRole.HELD_OUT,
        seed_start=held_out.seed_start,
        seed_count=seed_count,
    )


def _oracle(case: ArenaEvaluationCase) -> PaymentLinkCaseOracle:
    payment = case.oracle.provider_plan.initial_state
    expected = case.oracle.expected_incident_type is IncidentType.FAILED_WITHOUT_RECOVERY
    eligible = bool(
        expected
        and case.oracle.expected_affected_entity is not None
        and case.oracle.expected_affected_entity.entity_id == payment.payment_id
        and payment.status is PaymentStatus.FAILED
        and not payment.captured
        and payment.amount.amount_subunits <= _MAXIMUM_LINK_SUBUNITS
    )
    fault = tuple(PaymentLinkFault)[
        int(case.observed.observed_case_sha256[:8], 16) % len(PaymentLinkFault)
    ]
    recoverable = eligible and fault in {
        PaymentLinkFault.PAID,
        PaymentLinkFault.DUPLICATE_PAID_WEBHOOK,
        PaymentLinkFault.PAID_WITH_LOST_CREATE_RESPONSE,
    }
    draft = PaymentLinkCaseOracle.model_construct(
        case_id=case.observed.case_id,
        expected_incident=expected,
        action_eligible=eligible,
        recoverable=recoverable,
        fault=fault,
        payment_id=payment.payment_id,
        amount=payment.amount,
        oracle_sha256="0" * 64,
    )
    return PaymentLinkCaseOracle.model_validate(
        {
            **draft.model_dump(mode="json"),
            "oracle_sha256": _model_hash(draft, exclude={"oracle_sha256"}),
        }
    )


async def _run_no_intervention(case: ArenaEvaluationCase) -> PaymentLinkStrategyObservation:
    return PaymentLinkStrategyObservation(
        strategy=PaymentLinkStrategyName.NO_INTERVENTION,
        case_id=case.observed.case_id,
        audit_root_sha256=empty_control_audit_root(),
    )


async def _run_link_every_failed(
    case: ArenaEvaluationCase,
    gateway: RazorpayPaymentGateway,
) -> PaymentLinkStrategyObservation:
    payment = _latest_payment(case.observed)
    if payment.effective_payment_status is not PaymentStatus.FAILED or payment.amount is None:
        return PaymentLinkStrategyObservation(
            strategy=PaymentLinkStrategyName.LINK_EVERY_FAILED_PAYMENT,
            case_id=case.observed.case_id,
            audit_root_sha256=empty_control_audit_root(),
        )
    payment_id = payment.entity.entity_id
    try:
        current = await gateway.fetch_payment(payment_id)
        await gateway.create_payment_link(
            amount=current.amount,
            reference_id=(current.order_id or current.payment_id)[:40],
            description="Blind failed-payment retry",
            expire_by=case.observed.evaluated_at + timedelta(seconds=_LINK_TTL_SECONDS),
        )
    except RazorpayActionError as failure:
        return PaymentLinkStrategyObservation(
            strategy=PaymentLinkStrategyName.LINK_EVERY_FAILED_PAYMENT,
            case_id=case.observed.case_id,
            action_attempted=True,
            target_payment_id=payment_id,
            stable_error_code=failure.code.value,
            audit_root_sha256=empty_control_audit_root(),
        )
    return PaymentLinkStrategyObservation(
        strategy=PaymentLinkStrategyName.LINK_EVERY_FAILED_PAYMENT,
        case_id=case.observed.case_id,
        action_attempted=True,
        target_payment_id=payment_id,
        provider_returned_success=True,
        audit_root_sha256=empty_control_audit_root(),
    )


async def _run_chakravyuh(
    case: ArenaEvaluationCase,
    gateway: RazorpayPaymentGateway,
) -> PaymentLinkStrategyObservation:
    observed = case.observed
    state = reduce_payment_journey(list(observed.events))
    findings = (
        DeterministicPaymentInvariantEvaluator()
        .evaluate(
            state,
            observed.events,
            as_of=observed.evaluated_at,
        )
        .findings
    )
    supported = tuple(
        finding
        for finding in findings
        if finding.incident_type is IncidentType.FAILED_WITHOUT_RECOVERY
    )
    if len(supported) != 1:
        return PaymentLinkStrategyObservation(
            strategy=PaymentLinkStrategyName.CHAKRAVYUH,
            case_id=observed.case_id,
            detected_expected_incident=bool(supported),
            audit_root_sha256=empty_control_audit_root(),
        )
    finding = supported[0]
    identities = _CaseUuidFactory(observed.case_id)
    clock = _FixedClock(observed.evaluated_at)
    seed = _proposal_seed(observed, finding)
    repository = ArenaRecoveryActionRepository(seed, clock=clock, uuid_factory=identities)
    policy = DeterministicRecoveryPolicy(
        RecoveryPolicyConfig(
            actions_enabled=True,
            test_credentials=True,
            merchant_id=observed.merchant_id,
            maximum_payment_link_subunits=_MAXIMUM_LINK_SUBUNITS,
            minimum_payment_link_confidence=0.9,
        ),
        uuid_factory=identities,
    )
    control = RecoveryActionControlPlane(
        repository,
        policy,
        gateway,
        proposal_ttl_seconds=900,
        execution_lease_seconds=30,
        recovery_link_ttl_seconds=_LINK_TTL_SECONDS,
        clock=clock,
        uuid_factory=identities,
    )
    proposal = await control.propose(
        seed.incident_id,
        principal_id=_MAKER,
        request_id=f"{observed.case_id}:propose",
    )
    if proposal.policy.outcome is not PolicyOutcome.REQUIRE_APPROVAL:
        return _action_observation(observed, repository, proposal, policy_denied=True)
    approved = _checker_approves(observed, finding, proposal)
    reviewed = await control.decide(
        proposal.proposal.proposal_id,
        principal_id=_CHECKER,
        request_id=f"{observed.case_id}:review",
        decision=(ActionApprovalDecision.APPROVED if approved else ActionApprovalDecision.REJECTED),
        rationale="Independent checker verified failed-payment evidence, target and exact amount.",
    )
    if not approved:
        return _action_observation(observed, repository, reviewed, checker_review_count=1)
    executed = await control.execute(
        proposal.proposal.proposal_id,
        principal_id=_EXECUTOR,
        request_id=f"{observed.case_id}:execute",
    )
    return _action_observation(
        observed,
        repository,
        executed,
        checker_review_count=1,
        action_attempted=True,
    )


async def run_payment_link_arena(
    *,
    code_revision: str,
    seed_count: int = 667,
) -> PaymentLinkArenaReport:
    if len(code_revision) != 40 or any(
        character not in "0123456789abcdef" for character in code_revision
    ):
        raise ValueError("code revision must be a lowercase 40-character Git SHA")
    contract = create_payment_link_arena_contract()
    portfolio = generate_payment_link_arena_portfolio(seed_count=seed_count)
    oracles = tuple(_oracle(case) for case in portfolio.cases)
    strategy_results: list[PaymentLinkStrategyMetrics] = []
    for strategy in PaymentLinkStrategyName:
        results = tuple(
            [
                await _evaluate(case, oracle, strategy)
                for case, oracle in zip(portfolio.cases, oracles, strict=True)
            ]
        )
        strategy_results.append(_metrics(strategy, results, oracles))
    metrics = tuple(strategy_results)
    draft = PaymentLinkArenaReport.model_construct(
        code_revision=code_revision,
        contract=contract,
        base_portfolio_manifest_sha256=portfolio.manifest.manifest_sha256,
        oracle_root_sha256=_merkle_root(sorted(item.oracle_sha256 for item in oracles)),
        strategies=metrics,
        fault_counts=dict(sorted(Counter(item.fault.value for item in oracles).items())),
        claims_boundary=(
            "Deterministic synthetic INR outcomes over provider-shaped Test Mode semantics; "
            "not merchant revenue, customer conversion, or a production SLA."
        ),
        passed=_report_passed(metrics),
        report_sha256="0" * 64,
    )
    return PaymentLinkArenaReport.model_validate(
        {
            **draft.model_dump(mode="json"),
            "report_sha256": _model_hash(draft, exclude={"report_sha256"}),
        }
    )


async def _evaluate(
    case: ArenaEvaluationCase,
    oracle: PaymentLinkCaseOracle,
    strategy: PaymentLinkStrategyName,
) -> PaymentLinkCaseResult:
    twin = _PaymentLinkTwin(case, oracle)
    if strategy is PaymentLinkStrategyName.NO_INTERVENTION:
        observation = await _run_no_intervention(case)
    elif strategy is PaymentLinkStrategyName.LINK_EVERY_FAILED_PAYMENT:
        observation = await _run_link_every_failed(case, twin.gateway())
    else:
        observation = await _run_chakravyuh(case, twin.gateway())
    deliveries = twin.drain_confirmations()
    operation_count, creation_count, snapshot_hash = twin.snapshot()
    confirmations = {
        item.source_event_id for item in deliveries if item.event_type == "payment_link.paid"
    }
    exact_target = observation.target_payment_id == oracle.payment_id
    correct = observation.action_attempted and oracle.action_eligible and exact_target
    incorrect = observation.action_attempted and not correct
    provider_confirmed = bool(confirmations)
    recovered = oracle.recoverable and provider_confirmed
    expected = oracle.expected_incident
    predicted = observation.detected_expected_incident
    draft = PaymentLinkCaseResult.model_construct(
        case_id=oracle.case_id,
        strategy=strategy,
        detection_true_positive=(
            strategy is PaymentLinkStrategyName.CHAKRAVYUH and expected and predicted
        ),
        detection_false_positive=(
            strategy is PaymentLinkStrategyName.CHAKRAVYUH and predicted and not expected
        ),
        detection_false_negative=(
            strategy is PaymentLinkStrategyName.CHAKRAVYUH and expected and not predicted
        ),
        action_attempted=observation.action_attempted,
        correct_action=correct,
        incorrect_action=incorrect,
        provider_returned_success=observation.provider_returned_success,
        provider_confirmed=provider_confirmed,
        confirmed_recovery=recovered,
        recoverable_missed=oracle.recoverable and not recovered,
        provider_operation_count=operation_count,
        applied_link_creation_count=creation_count,
        duplicate_link_creation_count=max(0, creation_count - 1),
        confirmation_delivery_count=len(deliveries),
        unique_confirmation_count=len(confirmations),
        recovered_subunits=oracle.amount.amount_subunits if recovered else 0,
        manual_review_cost_subunits=(
            observation.checker_review_count * _MANUAL_REVIEW_COST_SUBUNITS
        ),
        incorrect_action_cost_subunits=(_INCORRECT_ACTION_COST_SUBUNITS if incorrect else 0),
        stable_error_code=observation.stable_error_code,
        audit_root_sha256=observation.audit_root_sha256,
        provider_snapshot_sha256=snapshot_hash,
        result_sha256="0" * 64,
    )
    return PaymentLinkCaseResult.model_validate(
        {
            **draft.model_dump(mode="json"),
            "result_sha256": _model_hash(draft, exclude={"result_sha256"}),
        }
    )


def _metrics(
    strategy: PaymentLinkStrategyName,
    results: tuple[PaymentLinkCaseResult, ...],
    oracles: tuple[PaymentLinkCaseOracle, ...],
) -> PaymentLinkStrategyMetrics:
    attempts = sum(item.action_attempted for item in results)
    correct = sum(item.correct_action for item in results)
    eligible = sum(item.action_eligible for item in oracles)
    true_positive = sum(item.detection_true_positive for item in results)
    false_positive = sum(item.detection_false_positive for item in results)
    false_negative = sum(item.detection_false_negative for item in results)
    recovered = sum(item.recovered_subunits for item in results)
    review_cost = sum(item.manual_review_cost_subunits for item in results)
    incorrect_cost = sum(item.incorrect_action_cost_subunits for item in results)
    return PaymentLinkStrategyMetrics(
        strategy=strategy,
        case_count=len(results),
        expected_incident_count=sum(item.expected_incident for item in oracles),
        action_eligible_count=eligible,
        oracle_recoverable_count=sum(item.recoverable for item in oracles),
        action_attempt_count=attempts,
        correct_action_count=correct,
        incorrect_action_count=sum(item.incorrect_action for item in results),
        confirmed_recovery_count=sum(item.confirmed_recovery for item in results),
        missed_recoverable_count=sum(item.recoverable_missed for item in results),
        duplicate_link_creation_count=sum(item.duplicate_link_creation_count for item in results),
        confirmation_delivery_count=sum(item.confirmation_delivery_count for item in results),
        unique_confirmation_count=sum(item.unique_confirmation_count for item in results),
        detection_precision=(
            None
            if strategy is not PaymentLinkStrategyName.CHAKRAVYUH
            or true_positive + false_positive == 0
            else true_positive / (true_positive + false_positive)
        ),
        detection_recall=(
            None
            if strategy is not PaymentLinkStrategyName.CHAKRAVYUH
            or true_positive + false_negative == 0
            else true_positive / (true_positive + false_negative)
        ),
        action_precision=None if attempts == 0 else correct / attempts,
        action_recall=1.0 if eligible == 0 else correct / eligible,
        recovered_subunits=recovered,
        manual_review_cost_subunits=review_cost,
        incorrect_action_cost_subunits=incorrect_cost,
        net_recovery_value_subunits=recovered - review_cost - incorrect_cost,
        results_root_sha256=_merkle_root(sorted(item.result_sha256 for item in results)),
    )


def _proposal_seed(observed: ArenaObservedCase, finding: InvariantFinding) -> ActionProposalSeed:
    identity = f"chakravyuh:payment-link-arena:{observed.case_id}:{finding.incident_key}"
    return ActionProposalSeed(
        incident_id=uuid5(NAMESPACE_URL, f"{identity}:incident"),
        source_revision_id=uuid5(NAMESPACE_URL, f"{identity}:revision"),
        diagnosis_id=uuid5(NAMESPACE_URL, f"{identity}:diagnosis"),
        merchant_id=observed.merchant_id,
        incident_type=IncidentType.FAILED_WITHOUT_RECOVERY,
        incident_status=IncidentStatus.DETECTED,
        target=finding.affected_entity,
        amount_at_risk=finding.amount_at_risk,
        action_type=ActionType.CREATE_PAYMENT_LINK,
        rationale="Failed payment has no later provider-confirmed recovery.",
        evidence_ids=tuple(item.evidence_id for item in finding.evidence),
        confidence=1.0,
    )


def _checker_approves(
    observed: ArenaObservedCase,
    finding: InvariantFinding,
    view: ActionView,
) -> bool:
    proposal = view.proposal
    return bool(
        view.policy.outcome is PolicyOutcome.REQUIRE_APPROVAL
        and proposal.incident_type is IncidentType.FAILED_WITHOUT_RECOVERY
        and proposal.action_type is ActionType.CREATE_PAYMENT_LINK
        and proposal.target == finding.affected_entity
        and proposal.amount == finding.amount_at_risk
        and proposal.merchant_id == observed.merchant_id
        and proposal.evidence_ids
        and proposal.confidence >= 0.9
    )


def _action_observation(
    observed: ArenaObservedCase,
    repository: ArenaRecoveryActionRepository,
    view: ActionView,
    *,
    policy_denied: bool = False,
    checker_review_count: int = 0,
    action_attempted: bool = False,
) -> PaymentLinkStrategyObservation:
    result = view.latest_result
    return PaymentLinkStrategyObservation(
        strategy=PaymentLinkStrategyName.CHAKRAVYUH,
        case_id=observed.case_id,
        detected_expected_incident=True,
        proposal_created=True,
        policy_denied=policy_denied,
        checker_review_count=checker_review_count,
        action_attempted=action_attempted,
        target_payment_id=view.proposal.target.entity_id if action_attempted else None,
        provider_returned_success=(view.execution_status is ActionExecutionStatus.SUCCEEDED),
        stable_error_code=None if result is None else result.error_code,
        audit_root_sha256=repository.audit_root_sha256,
    )


def _latest_payment(observed: ArenaObservedCase) -> JourneyEntityState:
    state = reduce_payment_journey(list(observed.events))
    payments = [item for item in state.entities if item.entity.entity_type is EntityType.PAYMENT]
    if not payments:
        raise ValueError("arena case has no payment")
    return max(payments, key=lambda item: (item.last_occurred_at, item.entity.entity_id))


def _report_passed(metrics: tuple[PaymentLinkStrategyMetrics, ...]) -> bool:
    if len(metrics) != 3:
        return False
    no_action, blind, guarded = metrics
    return bool(
        guarded.detection_precision == 1.0
        and guarded.detection_recall == 1.0
        and guarded.action_precision == 1.0
        and guarded.action_recall == 1.0
        and guarded.incorrect_action_count == 0
        and guarded.duplicate_link_creation_count == 0
        and guarded.confirmed_recovery_count == blind.confirmed_recovery_count
        and guarded.net_recovery_value_subunits > no_action.net_recovery_value_subunits
        and guarded.net_recovery_value_subunits > blind.net_recovery_value_subunits
    )


def _model_hash(model: BaseModel, *, exclude: set[str]) -> str:
    return _canonical_hash(model.model_dump(mode="json", exclude=exclude))


def _canonical_hash(value: object) -> str:
    body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()


def _merkle_root(leaves: list[str]) -> str:
    if not leaves:
        return hashlib.sha256(b"chakravyuh:payment-link-arena:empty").hexdigest()
    level = leaves
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(f"{level[index]}:{level[index + 1]}".encode()).hexdigest()
            for index in range(0, len(level), 2)
        ]
    return level[0]
