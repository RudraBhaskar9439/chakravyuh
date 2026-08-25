"""Held-out tournament for Chakravyuh's complete guarded recovery path."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chakravyuh.application.ports import RazorpayPaymentGateway
from chakravyuh.application.recovery_actions import RecoveryActionControlPlane
from chakravyuh.domain.action_policy import DeterministicRecoveryPolicy, RecoveryPolicyConfig
from chakravyuh.domain.actions import ActionProposalSeed, ActionView
from chakravyuh.domain.enums import (
    ActionApprovalDecision,
    ActionExecutionStatus,
    ActionType,
    IncidentStatus,
    IncidentType,
    PolicyOutcome,
)
from chakravyuh.domain.invariants import (
    DeterministicPaymentInvariantEvaluator,
    InvariantFinding,
)
from chakravyuh.domain.journeys import reduce_payment_journey
from chakravyuh.domain.recovery_arena import (
    ArenaStrategyName,
    RecoveryArenaContract,
)
from chakravyuh.simulation.arena_action_repository import (
    ArenaRecoveryActionRepository,
    empty_control_audit_root,
)
from chakravyuh.simulation.razorpay_twin import DeterministicRazorpayTwin
from chakravyuh.simulation.recovery_baselines import (
    ArenaBaselineReport,
    ArenaScoredCaseResult,
    ArenaStrategyMetrics,
    run_baseline_tournament,
)
from chakravyuh.simulation.recovery_portfolio import (
    ArenaEvaluationCase,
    ArenaObservedCase,
    RecoveryPortfolio,
)

TOURNAMENT_VERSION = "recovery-arena-tournament-v1"
_MAKER = "arena-maker"
_CHECKER = "arena-checker"
_EXECUTOR = "arena-executor"


class ChakravyuhCaseObservation(BaseModel):
    """Strategy-owned facts produced without access to evaluator oracle fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    detected_incident_types: tuple[IncidentType, ...]
    finding_count: int = Field(ge=0)
    supported_finding_count: int = Field(ge=0)
    proposal_created: bool
    proposal_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    policy_outcome: PolicyOutcome | None = None
    policy_reasons: tuple[str, ...] = ()
    checker_review_count: int = Field(ge=0, le=1)
    checker_approved: bool
    action_attempted: bool
    action_type: ActionType | None = None
    target_payment_id: str | None = None
    provider_returned_success: bool
    execution_status: ActionExecutionStatus | None = None
    stable_error_code: str | None = None
    execution_result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    control_audit_event_count: int = Field(ge=0)
    control_audit_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    live_model_call_count: int = Field(default=0, ge=0)
    live_model_cost_microusd: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_control_flow(self) -> ChakravyuhCaseObservation:
        if self.proposal_created != (self.proposal_hash is not None):
            msg = "arena proposal flag must agree with its immutable proposal hash"
            raise ValueError(msg)
        if self.checker_approved and self.checker_review_count != 1:
            msg = "arena checker approval requires exactly one independent review"
            raise ValueError(msg)
        if self.action_attempted and (
            not self.checker_approved
            or self.action_type is not ActionType.CAPTURE_PAYMENT
            or self.target_payment_id is None
        ):
            msg = "arena mutation attempt requires an approved exact capture target"
            raise ValueError(msg)
        if self.execution_status is None and self.execution_result_hash is not None:
            msg = "arena execution result hash requires an execution status"
            raise ValueError(msg)
        return self


class ChakravyuhScoredCaseResult(BaseModel):
    """Evaluator-owned binding of one strategy trace to oracle and provider evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    detection_true_positive_count: int = Field(ge=0)
    detection_false_positive_count: int = Field(ge=0)
    detection_false_negative_count: int = Field(ge=0)
    exact_executable_target: bool | None = None
    proposal_created: bool
    policy_denied: bool
    checker_review_count: int = Field(ge=0, le=1)
    action_attempted: bool
    correct_action: bool
    incorrect_action: bool
    eligible_action_missed: bool
    provider_returned_success: bool
    provider_confirmed: bool
    confirmed_recovery: bool
    recoverable_missed: bool
    stable_error_code: str | None = None
    provider_operation_count: int = Field(ge=0)
    applied_mutation_count: int = Field(ge=0)
    recovered_subunits: int = Field(ge=0)
    manual_review_cost_subunits: int = Field(ge=0)
    incorrect_action_cost_subunits: int = Field(ge=0)
    control_audit_event_count: int = Field(ge=0)
    control_audit_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_score(self) -> ChakravyuhScoredCaseResult:
        if self.correct_action and (not self.action_attempted or self.incorrect_action):
            msg = "arena correct action must be an attempted, non-incorrect action"
            raise ValueError(msg)
        if self.confirmed_recovery and not self.provider_confirmed:
            msg = "arena recovery requires independent provider confirmation"
            raise ValueError(msg)
        if _model_hash(self, exclude={"result_sha256"}) != self.result_sha256:
            msg = "arena Chakravyuh result hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ArenaTournamentStrategyMetrics(BaseModel):
    """Comparable safety, revenue, and operational totals for one strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: ArenaStrategyName
    case_count: int = Field(ge=1)
    oracle_action_eligible_count: int = Field(ge=0)
    oracle_recoverable_count: int = Field(ge=0)
    detection_true_positive_count: int | None = Field(default=None, ge=0)
    detection_false_positive_count: int | None = Field(default=None, ge=0)
    detection_false_negative_count: int | None = Field(default=None, ge=0)
    detection_precision: float | None = Field(default=None, ge=0, le=1)
    detection_recall: float | None = Field(default=None, ge=0, le=1)
    detection_f1: float | None = Field(default=None, ge=0, le=1)
    proposal_count: int = Field(ge=0)
    policy_denial_count: int = Field(ge=0)
    checker_review_count: int = Field(ge=0)
    action_attempt_count: int = Field(ge=0)
    correct_action_count: int = Field(ge=0)
    incorrect_action_count: int = Field(ge=0)
    eligible_action_missed_count: int = Field(ge=0)
    action_precision: float | None = Field(default=None, ge=0, le=1)
    action_recall: float = Field(ge=0, le=1)
    provider_confirmed_count: int = Field(ge=0)
    confirmed_recovery_count: int = Field(ge=0)
    missed_recoverable_count: int = Field(ge=0)
    provider_operation_count: int = Field(ge=0)
    applied_mutation_count: int = Field(ge=0)
    duplicate_mutation_count: int = Field(ge=0)
    oracle_recoverable_revenue_subunits: int = Field(ge=0)
    confirmed_recovered_revenue_subunits: int = Field(ge=0)
    manual_review_cost_subunits: int = Field(ge=0)
    incorrect_action_cost_subunits: int = Field(ge=0)
    net_recovery_value_subunits: int
    recovery_efficiency: float = Field(ge=0, le=1)
    live_model_call_count: int = Field(ge=0)
    live_model_cost_microusd: int = Field(ge=0)
    results_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RecoveryArenaTournamentReport(BaseModel):
    """Tamper-evident three-way result with explicit acceptance gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: str = TOURNAMENT_VERSION
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    portfolio_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategies: tuple[ArenaTournamentStrategyMetrics, ...]
    chakravyuh_control_audit_roots_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_report(self) -> RecoveryArenaTournamentReport:
        if tuple(item.strategy for item in self.strategies) != tuple(ArenaStrategyName):
            msg = "arena tournament requires all strategies in canonical order"
            raise ValueError(msg)
        if self.passed != _tournament_passed(self.strategies):
            msg = "arena tournament pass flag must match its safety and value gates"
            raise ValueError(msg)
        if _model_hash(self, exclude={"report_sha256"}) != self.report_sha256:
            msg = "arena tournament report hash does not match its canonical content"
            raise ValueError(msg)
        return self


class _CaseUuidFactory:
    def __init__(self, case_id: str) -> None:
        self._case_id = case_id
        self._sequence = 0

    def __call__(self) -> UUID:
        self._sequence += 1
        return uuid5(
            NAMESPACE_URL,
            f"chakravyuh:recovery-arena:{self._case_id}:control-id:{self._sequence}",
        )


class ChakravyuhRecoveryStrategy:
    """Use production reducers and action controls, with no evaluator-oracle dependency."""

    name = ArenaStrategyName.CHAKRAVYUH

    async def run(
        self,
        observed: ArenaObservedCase,
        gateway: RazorpayPaymentGateway,
    ) -> ChakravyuhCaseObservation:
        state = reduce_payment_journey(list(observed.events))
        evaluation = DeterministicPaymentInvariantEvaluator().evaluate(
            state,
            observed.events,
            as_of=observed.evaluated_at,
        )
        supported = tuple(
            item
            for item in evaluation.findings
            if item.incident_type is IncidentType.AUTHORIZED_NOT_CAPTURED
        )
        detected_types = tuple(sorted({item.incident_type for item in evaluation.findings}))
        if len(supported) != 1:
            return _inactive_observation(
                observed,
                detected_types=detected_types,
                finding_count=len(evaluation.findings),
                supported_finding_count=len(supported),
            )

        finding = supported[0]
        identity_factory = _CaseUuidFactory(observed.case_id)
        clock = _FixedClock(observed.evaluated_at)
        seed = _proposal_seed(observed, finding)
        repository = ArenaRecoveryActionRepository(
            seed,
            clock=clock,
            uuid_factory=identity_factory,
        )
        policy = DeterministicRecoveryPolicy(
            RecoveryPolicyConfig(
                actions_enabled=observed.merchant_policy.capture_enabled,
                test_credentials=True,
                merchant_id=observed.merchant_id,
                maximum_capture_subunits=(observed.merchant_policy.maximum_capture_subunits),
                minimum_capture_confidence=0.9,
                allowed_capture_currencies=frozenset({"INR"}),
            ),
            uuid_factory=identity_factory,
        )
        control = RecoveryActionControlPlane(
            repository,
            policy,
            gateway,
            proposal_ttl_seconds=900,
            execution_lease_seconds=30,
            clock=clock,
            uuid_factory=identity_factory,
        )
        proposal = await control.propose(
            seed.incident_id,
            principal_id=_MAKER,
            request_id=f"{observed.case_id}:propose",
        )
        if proposal.policy.outcome is not PolicyOutcome.REQUIRE_APPROVAL:
            return _observation_from_view(
                observed,
                detected_types=detected_types,
                finding_count=len(evaluation.findings),
                supported_finding_count=1,
                repository=repository,
                proposal_created=True,
                checker_review_count=0,
                checker_approved=False,
                action_attempted=False,
                view=proposal,
            )

        checker_approved = _checker_approves(observed, finding, proposal)
        reviewed = await control.decide(
            proposal.proposal.proposal_id,
            principal_id=_CHECKER,
            request_id=f"{observed.case_id}:review",
            decision=(
                ActionApprovalDecision.APPROVED
                if checker_approved
                else ActionApprovalDecision.REJECTED
            ),
            rationale=(
                "Independent checker verified policy, evidence, exact amount, and payment target."
                if checker_approved
                else "Independent checker rejected a mismatched recovery proposal."
            ),
        )
        if not checker_approved:
            return _observation_from_view(
                observed,
                detected_types=detected_types,
                finding_count=len(evaluation.findings),
                supported_finding_count=1,
                repository=repository,
                proposal_created=True,
                checker_review_count=1,
                checker_approved=False,
                action_attempted=False,
                view=reviewed,
            )
        executed = await control.execute(
            proposal.proposal.proposal_id,
            principal_id=_EXECUTOR,
            request_id=f"{observed.case_id}:execute",
        )
        return _observation_from_view(
            observed,
            detected_types=detected_types,
            finding_count=len(evaluation.findings),
            supported_finding_count=1,
            repository=repository,
            proposal_created=True,
            checker_review_count=1,
            checker_approved=True,
            action_attempted=True,
            view=executed,
        )


class _FixedClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def __call__(self) -> datetime:
        return self._value


async def run_recovery_tournament(
    portfolio: RecoveryPortfolio,
    contract: RecoveryArenaContract,
) -> tuple[
    RecoveryArenaTournamentReport,
    tuple[ChakravyuhScoredCaseResult, ...],
    ArenaBaselineReport,
]:
    """Run all locked strategies on independent twins and return committed evidence."""

    baseline_report, baseline_results = await run_baseline_tournament(portfolio, contract)
    strategy = ChakravyuhRecoveryStrategy()
    chakravyuh_results = tuple(
        [await _evaluate_chakravyuh_case(item, strategy, contract) for item in portfolio.cases]
    )
    baseline_metrics = tuple(
        _baseline_metrics(item, baseline_results, portfolio) for item in baseline_report.strategies
    )
    chakravyuh_metrics = _chakravyuh_metrics(chakravyuh_results, portfolio, contract)
    metrics = (*baseline_metrics, chakravyuh_metrics)
    audit_root = _merkle_root(sorted(item.control_audit_root_sha256 for item in chakravyuh_results))
    passed = _tournament_passed(metrics)
    draft = RecoveryArenaTournamentReport.model_construct(
        report_version=TOURNAMENT_VERSION,
        contract_sha256=contract.contract_sha256,
        portfolio_manifest_sha256=portfolio.manifest.manifest_sha256,
        baseline_report_sha256=baseline_report.report_sha256,
        strategies=metrics,
        chakravyuh_control_audit_roots_sha256=audit_root,
        passed=passed,
        report_sha256="0" * 64,
    )
    report = RecoveryArenaTournamentReport.model_validate(
        {
            **draft.model_dump(mode="json"),
            "report_sha256": _model_hash(draft, exclude={"report_sha256"}),
        }
    )
    return report, chakravyuh_results, baseline_report


async def _evaluate_chakravyuh_case(
    case: ArenaEvaluationCase,
    strategy: ChakravyuhRecoveryStrategy,
    contract: RecoveryArenaContract,
) -> ChakravyuhScoredCaseResult:
    twin = DeterministicRazorpayTwin(case.oracle.provider_plan)
    observation = await strategy.run(case.observed, twin.strategy_gateway())
    webhooks = await twin.drain_webhooks()
    snapshot = await twin.snapshot()
    confirmations = {
        item.source_event_id
        for item in webhooks
        if item.event_type in contract.confirmation_event_types
    }
    expected_types = (
        set()
        if case.oracle.expected_incident_type is None
        else {case.oracle.expected_incident_type}
    )
    predicted_types = set(observation.detected_incident_types)
    exact_target = None
    if observation.action_attempted:
        exact_target = bool(
            observation.action_type is case.oracle.expected_action
            and case.oracle.expected_affected_entity is not None
            and observation.target_payment_id == case.oracle.expected_affected_entity.entity_id
        )
    correct_action = bool(
        observation.action_attempted and case.oracle.action_eligible and exact_target
    )
    incorrect_action = observation.action_attempted and not correct_action
    provider_confirmed = bool(confirmations)
    confirmed_recovery = case.oracle.recoverable and provider_confirmed
    recovered_subunits = case.oracle.payment_amount.amount_subunits if confirmed_recovery else 0
    draft = ChakravyuhScoredCaseResult.model_construct(
        case_id=case.observed.case_id,
        detection_true_positive_count=len(predicted_types & expected_types),
        detection_false_positive_count=len(predicted_types - expected_types),
        detection_false_negative_count=len(expected_types - predicted_types),
        exact_executable_target=exact_target,
        proposal_created=observation.proposal_created,
        policy_denied=observation.policy_outcome is PolicyOutcome.DENY,
        checker_review_count=observation.checker_review_count,
        action_attempted=observation.action_attempted,
        correct_action=correct_action,
        incorrect_action=incorrect_action,
        eligible_action_missed=case.oracle.action_eligible and not correct_action,
        provider_returned_success=observation.provider_returned_success,
        provider_confirmed=provider_confirmed,
        confirmed_recovery=confirmed_recovery,
        recoverable_missed=case.oracle.recoverable and not confirmed_recovery,
        stable_error_code=observation.stable_error_code,
        provider_operation_count=len(snapshot.operations),
        applied_mutation_count=snapshot.applied_mutation_count,
        recovered_subunits=recovered_subunits,
        manual_review_cost_subunits=(
            observation.checker_review_count * contract.manual_review_cost_subunits
        ),
        incorrect_action_cost_subunits=(
            contract.incorrect_action_cost_subunits if incorrect_action else 0
        ),
        control_audit_event_count=observation.control_audit_event_count,
        control_audit_root_sha256=observation.control_audit_root_sha256,
        provider_snapshot_sha256=snapshot.snapshot_sha256,
        result_sha256="0" * 64,
    )
    return ChakravyuhScoredCaseResult.model_validate(
        {
            **draft.model_dump(mode="json"),
            "result_sha256": _model_hash(draft, exclude={"result_sha256"}),
        }
    )


def _proposal_seed(
    observed: ArenaObservedCase,
    finding: InvariantFinding,
) -> ActionProposalSeed:
    identity = f"chakravyuh:recovery-arena:{observed.case_id}:{finding.incident_key}"
    return ActionProposalSeed(
        incident_id=uuid5(NAMESPACE_URL, f"{identity}:incident"),
        source_revision_id=uuid5(NAMESPACE_URL, f"{identity}:revision"),
        diagnosis_id=uuid5(NAMESPACE_URL, f"{identity}:diagnosis"),
        merchant_id=observed.merchant_id,
        incident_type=finding.incident_type,
        incident_status=IncidentStatus.DETECTED,
        target=finding.affected_entity,
        amount_at_risk=finding.amount_at_risk,
        action_type=ActionType.CAPTURE_PAYMENT,
        rationale=(
            "Deterministic invariant confirms that the payment remains authorized beyond the "
            "merchant capture grace window."
        ),
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
        observed.merchant_policy.independent_checker_required
        and view.policy.outcome is PolicyOutcome.REQUIRE_APPROVAL
        and proposal.incident_type is IncidentType.AUTHORIZED_NOT_CAPTURED
        and proposal.action_type is ActionType.CAPTURE_PAYMENT
        and proposal.target == finding.affected_entity
        and proposal.amount == finding.amount_at_risk
        and proposal.merchant_id == observed.merchant_id
        and proposal.evidence_ids
        and proposal.confidence >= 0.9
    )


def _inactive_observation(
    observed: ArenaObservedCase,
    *,
    detected_types: tuple[IncidentType, ...],
    finding_count: int,
    supported_finding_count: int,
) -> ChakravyuhCaseObservation:
    return ChakravyuhCaseObservation(
        case_id=observed.case_id,
        detected_incident_types=detected_types,
        finding_count=finding_count,
        supported_finding_count=supported_finding_count,
        proposal_created=False,
        checker_review_count=0,
        checker_approved=False,
        action_attempted=False,
        provider_returned_success=False,
        control_audit_event_count=0,
        control_audit_root_sha256=empty_control_audit_root(),
    )


def _observation_from_view(
    observed: ArenaObservedCase,
    *,
    detected_types: tuple[IncidentType, ...],
    finding_count: int,
    supported_finding_count: int,
    repository: ArenaRecoveryActionRepository,
    proposal_created: bool,
    checker_review_count: int,
    checker_approved: bool,
    action_attempted: bool,
    view: ActionView,
) -> ChakravyuhCaseObservation:
    result = view.latest_result
    return ChakravyuhCaseObservation(
        case_id=observed.case_id,
        detected_incident_types=detected_types,
        finding_count=finding_count,
        supported_finding_count=supported_finding_count,
        proposal_created=proposal_created,
        proposal_hash=view.proposal.proposal_hash,
        policy_outcome=view.policy.outcome,
        policy_reasons=view.policy.reasons,
        checker_review_count=checker_review_count,
        checker_approved=checker_approved,
        action_attempted=action_attempted,
        action_type=ActionType.CAPTURE_PAYMENT if action_attempted else None,
        target_payment_id=(view.proposal.target.entity_id if action_attempted else None),
        provider_returned_success=(view.execution_status is ActionExecutionStatus.SUCCEEDED),
        execution_status=view.execution_status if action_attempted else None,
        stable_error_code=None if result is None else result.error_code,
        execution_result_hash=None if result is None else result.result_hash,
        control_audit_event_count=len(repository.audit_events),
        control_audit_root_sha256=repository.audit_root_sha256,
    )


def _baseline_metrics(
    baseline: ArenaStrategyMetrics,
    results: tuple[ArenaScoredCaseResult, ...],
    portfolio: RecoveryPortfolio,
) -> ArenaTournamentStrategyMetrics:
    eligible = sum(item.oracle.action_eligible for item in portfolio.cases)
    correct = baseline.action_attempt_count - baseline.incorrect_action_count
    selected = tuple(item for item in results if item.strategy is baseline.strategy)
    return ArenaTournamentStrategyMetrics(
        strategy=baseline.strategy,
        case_count=baseline.case_count,
        oracle_action_eligible_count=eligible,
        oracle_recoverable_count=baseline.oracle_recoverable_count,
        proposal_count=0,
        policy_denial_count=0,
        checker_review_count=0,
        action_attempt_count=baseline.action_attempt_count,
        correct_action_count=correct,
        incorrect_action_count=baseline.incorrect_action_count,
        eligible_action_missed_count=max(0, eligible - correct),
        action_precision=(
            None if baseline.action_attempt_count == 0 else correct / baseline.action_attempt_count
        ),
        action_recall=1.0 if eligible == 0 else correct / eligible,
        provider_confirmed_count=baseline.provider_confirmed_count,
        confirmed_recovery_count=baseline.confirmed_recovery_count,
        missed_recoverable_count=baseline.missed_recoverable_count,
        provider_operation_count=baseline.provider_operation_count,
        applied_mutation_count=baseline.applied_mutation_count,
        duplicate_mutation_count=baseline.duplicate_mutation_count,
        oracle_recoverable_revenue_subunits=(baseline.oracle_recoverable_revenue_subunits),
        confirmed_recovered_revenue_subunits=(baseline.confirmed_recovered_revenue_subunits),
        manual_review_cost_subunits=0,
        incorrect_action_cost_subunits=baseline.incorrect_action_cost_subunits,
        net_recovery_value_subunits=baseline.net_recovery_value_subunits,
        recovery_efficiency=baseline.recovery_efficiency,
        live_model_call_count=0,
        live_model_cost_microusd=0,
        results_root_sha256=_merkle_root(sorted(item.result_sha256 for item in selected)),
    )


def _chakravyuh_metrics(
    results: tuple[ChakravyuhScoredCaseResult, ...],
    portfolio: RecoveryPortfolio,
    contract: RecoveryArenaContract,
) -> ArenaTournamentStrategyMetrics:
    eligible = sum(item.oracle.action_eligible for item in portfolio.cases)
    recoverable = sum(item.oracle.recoverable for item in portfolio.cases)
    recoverable_revenue = portfolio.manifest.oracle_recoverable_revenue_subunits
    tp = sum(item.detection_true_positive_count for item in results)
    fp = sum(item.detection_false_positive_count for item in results)
    fn = sum(item.detection_false_negative_count for item in results)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = _f1(precision, recall)
    actions = sum(item.action_attempted for item in results)
    correct = sum(item.correct_action for item in results)
    recovered = sum(item.recovered_subunits for item in results)
    review_cost = sum(item.manual_review_cost_subunits for item in results)
    incorrect_cost = sum(item.incorrect_action_cost_subunits for item in results)
    return ArenaTournamentStrategyMetrics(
        strategy=ArenaStrategyName.CHAKRAVYUH,
        case_count=len(results),
        oracle_action_eligible_count=eligible,
        oracle_recoverable_count=recoverable,
        detection_true_positive_count=tp,
        detection_false_positive_count=fp,
        detection_false_negative_count=fn,
        detection_precision=precision,
        detection_recall=recall,
        detection_f1=f1,
        proposal_count=sum(item.proposal_created for item in results),
        policy_denial_count=sum(item.policy_denied for item in results),
        checker_review_count=sum(item.checker_review_count for item in results),
        action_attempt_count=actions,
        correct_action_count=correct,
        incorrect_action_count=sum(item.incorrect_action for item in results),
        eligible_action_missed_count=sum(item.eligible_action_missed for item in results),
        action_precision=None if actions == 0 else correct / actions,
        action_recall=1.0 if eligible == 0 else correct / eligible,
        provider_confirmed_count=sum(item.provider_confirmed for item in results),
        confirmed_recovery_count=sum(item.confirmed_recovery for item in results),
        missed_recoverable_count=sum(item.recoverable_missed for item in results),
        provider_operation_count=sum(item.provider_operation_count for item in results),
        applied_mutation_count=sum(item.applied_mutation_count for item in results),
        duplicate_mutation_count=sum(max(0, item.applied_mutation_count - 1) for item in results),
        oracle_recoverable_revenue_subunits=recoverable_revenue,
        confirmed_recovered_revenue_subunits=recovered,
        manual_review_cost_subunits=review_cost,
        incorrect_action_cost_subunits=incorrect_cost,
        net_recovery_value_subunits=recovered - review_cost - incorrect_cost,
        recovery_efficiency=(1.0 if recoverable_revenue == 0 else recovered / recoverable_revenue),
        live_model_call_count=0,
        live_model_cost_microusd=0,
        results_root_sha256=_merkle_root(sorted(item.result_sha256 for item in results)),
    )


def _tournament_passed(strategies: tuple[ArenaTournamentStrategyMetrics, ...]) -> bool:
    if len(strategies) != 3:
        return False
    no_action, retry_all, chakravyuh = strategies
    return bool(
        chakravyuh.strategy is ArenaStrategyName.CHAKRAVYUH
        and chakravyuh.detection_precision == 1.0
        and chakravyuh.detection_recall == 1.0
        and chakravyuh.action_precision == 1.0
        and chakravyuh.action_recall == 1.0
        and chakravyuh.incorrect_action_count == 0
        and chakravyuh.eligible_action_missed_count == 0
        and chakravyuh.duplicate_mutation_count == 0
        and chakravyuh.confirmed_recovery_count >= retry_all.confirmed_recovery_count
        and chakravyuh.net_recovery_value_subunits > no_action.net_recovery_value_subunits
        and chakravyuh.net_recovery_value_subunits > retry_all.net_recovery_value_subunits
        and chakravyuh.live_model_call_count <= 100
        and chakravyuh.live_model_cost_microusd <= 1_000_000
        and retry_all.incorrect_action_count > 0
    )


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _model_hash(model: BaseModel, *, exclude: set[str]) -> str:
    return _canonical_hash(model.model_dump(mode="json", exclude=exclude))


def _merkle_root(hashes: Sequence[str]) -> str:
    if not hashes:
        msg = "arena tournament root requires at least one hash"
        raise ValueError(msg)
    layer = [bytes.fromhex(value) for value in hashes]
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [
            hashlib.sha256(layer[index] + layer[index + 1]).digest()
            for index in range(0, len(layer), 2)
        ]
    return layer[0].hex()


def _canonical_hash(value: object) -> str:
    body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()
