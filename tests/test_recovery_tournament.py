"""Three-way tournament, dual-control, and tamper-evidence proofs."""

import json
from collections.abc import Callable
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from pydantic import ValidationError

from chakravyuh.application.recovery_actions import RecoveryActionControlPlane
from chakravyuh.domain.action_policy import DeterministicRecoveryPolicy, RecoveryPolicyConfig
from chakravyuh.domain.actions import ActionProposalSeed
from chakravyuh.domain.enums import (
    ActionApprovalDecision,
    ActionExecutionStatus,
    ActionType,
    IncidentStatus,
    IncidentType,
)
from chakravyuh.domain.errors import ActionControlError, ActionControlErrorCode
from chakravyuh.domain.invariants import DeterministicPaymentInvariantEvaluator
from chakravyuh.domain.journeys import reduce_payment_journey
from chakravyuh.domain.recovery_arena import (
    ArenaDatasetRole,
    ArenaStrategyName,
    RecoveryArenaContract,
    create_recovery_arena_contract,
)
from chakravyuh.operations import recovery_arena_tournament as tournament_cli
from chakravyuh.simulation.arena_action_repository import ArenaRecoveryActionRepository
from chakravyuh.simulation.razorpay_twin import (
    ArenaProviderFault,
    DeterministicRazorpayTwin,
)
from chakravyuh.simulation.recovery_portfolio import (
    ArenaEvaluationCase,
    RecoveryPortfolio,
    generate_held_out_recovery_portfolio,
    generate_recovery_portfolio,
)
from chakravyuh.simulation.recovery_tournament import (
    ChakravyuhRecoveryStrategy,
    RecoveryArenaTournamentReport,
    run_recovery_tournament,
)


def _portfolio(seed_count: int = 10) -> tuple[RecoveryArenaContract, RecoveryPortfolio]:
    contract = create_recovery_arena_contract()
    return contract, generate_recovery_portfolio(
        contract,
        dataset_role=ArenaDatasetRole.VALIDATION,
        seed_start=40_000,
        seed_count=seed_count,
    )


def _eligible_normal_case(portfolio: RecoveryPortfolio) -> ArenaEvaluationCase:
    return next(
        item
        for item in portfolio.cases
        if item.oracle.action_eligible
        and item.oracle.provider_plan.capture_fault is ArenaProviderFault.NONE
    )


def _uuid_factory(case_id: str) -> Callable[[], UUID]:
    sequence = 0

    def create() -> UUID:
        nonlocal sequence
        sequence += 1
        return uuid5(NAMESPACE_URL, f"test:{case_id}:{sequence}")

    return create


def _seed(case: ArenaEvaluationCase) -> ActionProposalSeed:
    state = reduce_payment_journey(list(case.observed.events))
    findings = (
        DeterministicPaymentInvariantEvaluator()
        .evaluate(
            state,
            case.observed.events,
            as_of=case.observed.evaluated_at,
        )
        .findings
    )
    finding = next(
        item for item in findings if item.incident_type is IncidentType.AUTHORIZED_NOT_CAPTURED
    )
    return ActionProposalSeed(
        incident_id=uuid5(NAMESPACE_URL, f"test:{case.observed.case_id}:incident"),
        source_revision_id=uuid5(NAMESPACE_URL, f"test:{case.observed.case_id}:revision"),
        diagnosis_id=uuid5(NAMESPACE_URL, f"test:{case.observed.case_id}:diagnosis"),
        merchant_id=case.observed.merchant_id,
        incident_type=finding.incident_type,
        incident_status=IncidentStatus.DETECTED,
        target=finding.affected_entity,
        amount_at_risk=finding.amount_at_risk,
        action_type=ActionType.CAPTURE_PAYMENT,
        rationale="Authorized payment exceeded the merchant capture grace window.",
        evidence_ids=tuple(item.evidence_id for item in finding.evidence),
        confidence=1.0,
    )


async def test_tournament_is_safe_profitable_and_oracle_isolated() -> None:
    contract, portfolio = _portfolio()

    report, results, baseline = await run_recovery_tournament(portfolio, contract)
    no_action, retry_all, chakravyuh = report.strategies

    assert report.passed and baseline.passed
    assert tuple(item.strategy for item in report.strategies) == tuple(ArenaStrategyName)
    assert chakravyuh.detection_precision == chakravyuh.detection_recall == 1.0
    assert chakravyuh.action_precision == chakravyuh.action_recall == 1.0
    assert chakravyuh.incorrect_action_count == chakravyuh.duplicate_mutation_count == 0
    assert chakravyuh.confirmed_recovery_count == retry_all.confirmed_recovery_count
    assert chakravyuh.net_recovery_value_subunits > no_action.net_recovery_value_subunits
    assert chakravyuh.net_recovery_value_subunits > retry_all.net_recovery_value_subunits
    assert len(results) == portfolio.manifest.case_count
    assert all(item.control_audit_root_sha256 for item in results)

    observed = json.loads(portfolio.cases[0].observed.model_dump_json())
    assert "oracle" not in observed
    assert "recoverable" not in observed
    assert "provider_plan" not in observed


async def test_tournament_and_control_roots_are_reproducible() -> None:
    contract, portfolio = _portfolio(seed_count=2)

    first, first_results, _ = await run_recovery_tournament(portfolio, contract)
    second, second_results, _ = await run_recovery_tournament(portfolio, contract)

    assert first == second
    assert first_results == second_results


async def test_locked_held_out_tournament_has_stable_safety_and_value_commitment() -> None:
    contract = create_recovery_arena_contract()
    portfolio = generate_held_out_recovery_portfolio(contract)

    report, _, _ = await run_recovery_tournament(portfolio, contract)
    _, retry_all, chakravyuh = report.strategies

    assert report.report_sha256 == (
        "a8d43e61a391fcce4426888c3428df5686e33426eb188cd6f86c60ad602151e6"
    )
    assert report.chakravyuh_control_audit_roots_sha256 == (
        "2e6f973d05a4124aff35fb7beaf4ed8d49201ecb9317cb0c7d631c9a5d66296a"
    )
    assert chakravyuh.results_root_sha256 == (
        "a2fa448349d57c184fe74626f1ed2944bdef23ee3308a11bebbcfb8ede5572cf"
    )
    assert chakravyuh.detection_true_positive_count == 4_002
    assert chakravyuh.detection_false_positive_count == 0
    assert chakravyuh.detection_false_negative_count == 0
    assert chakravyuh.action_attempt_count == chakravyuh.correct_action_count == 457
    assert chakravyuh.incorrect_action_count == 0
    assert chakravyuh.confirmed_recovery_count == 402
    assert chakravyuh.manual_review_cost_subunits == 914_000
    assert chakravyuh.net_recovery_value_subunits == 14_814_000
    assert retry_all.net_recovery_value_subunits == -19_722_000


async def test_real_control_plane_enforces_dual_control_and_idempotent_execution() -> None:
    _, portfolio = _portfolio()
    case = _eligible_normal_case(portfolio)

    def clock() -> datetime:
        return case.observed.evaluated_at

    identities = _uuid_factory(case.observed.case_id)
    seed = _seed(case)
    repository = ArenaRecoveryActionRepository(
        seed,
        clock=clock,
        uuid_factory=identities,
    )
    twin = DeterministicRazorpayTwin(case.oracle.provider_plan)
    policy = DeterministicRecoveryPolicy(
        RecoveryPolicyConfig(
            actions_enabled=True,
            test_credentials=True,
            merchant_id=case.observed.merchant_id,
            maximum_capture_subunits=case.observed.merchant_policy.maximum_capture_subunits,
        ),
        uuid_factory=identities,
    )
    control = RecoveryActionControlPlane(
        repository,
        policy,
        twin.strategy_gateway(),
        proposal_ttl_seconds=900,
        execution_lease_seconds=30,
        clock=clock,
        uuid_factory=identities,
    )
    proposal = await control.propose(
        seed.incident_id,
        principal_id="maker",
        request_id="propose",
    )

    with pytest.raises(ActionControlError) as missing_approval:
        await control.execute(
            proposal.proposal.proposal_id,
            principal_id="executor",
            request_id="execute-without-approval",
        )
    assert missing_approval.value.code is ActionControlErrorCode.APPROVAL_REQUIRED

    with pytest.raises(ActionControlError) as same_person:
        await control.decide(
            proposal.proposal.proposal_id,
            principal_id="maker",
            request_id="self-approve",
            decision=ActionApprovalDecision.APPROVED,
            rationale="invalid self approval",
        )
    assert same_person.value.code is ActionControlErrorCode.MAKER_CHECKER_VIOLATION

    await control.decide(
        proposal.proposal.proposal_id,
        principal_id="checker",
        request_id="approve",
        decision=ActionApprovalDecision.APPROVED,
        rationale="independent evidence review passed",
    )
    first = await control.execute(
        proposal.proposal.proposal_id,
        principal_id="executor",
        request_id="execute",
    )
    second = await control.execute(
        proposal.proposal.proposal_id,
        principal_id="executor",
        request_id="execute-again",
    )
    snapshot = await twin.snapshot()

    assert first.execution_status is second.execution_status is ActionExecutionStatus.SUCCEEDED
    assert snapshot.applied_mutation_count == 1
    assert repository.mutation_attempted
    assert repository.audit_events[-1].action == "execution_idempotent"


async def test_strategy_uses_observed_input_and_narrow_gateway_only() -> None:
    _, portfolio = _portfolio(seed_count=10)
    case = _eligible_normal_case(portfolio)
    twin = DeterministicRazorpayTwin(case.oracle.provider_plan)

    observation = await ChakravyuhRecoveryStrategy().run(
        case.observed,
        twin.strategy_gateway(),
    )

    assert observation.action_attempted
    assert observation.checker_approved
    assert observation.live_model_call_count == observation.live_model_cost_microusd == 0
    assert observation.control_audit_event_count >= 6


async def test_tournament_cli_emits_all_three_evidence_layers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, portfolio = _portfolio(seed_count=10)
    monkeypatch.setattr(
        tournament_cli,
        "generate_held_out_recovery_portfolio",
        lambda _: portfolio,
    )

    assert await tournament_cli._run() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["portfolio_manifest"]["case_count"] == 150
    assert output["baseline_report"]["passed"] is True
    assert output["tournament_report"]["passed"] is True


async def test_tournament_report_rejects_hash_and_gate_tampering() -> None:
    contract, portfolio = _portfolio(seed_count=10)
    report, _, _ = await run_recovery_tournament(portfolio, contract)

    with pytest.raises(ValidationError, match="report hash"):
        RecoveryArenaTournamentReport.model_validate(
            {**report.model_dump(), "report_sha256": "f" * 64}
        )
    with pytest.raises(ValidationError, match="pass flag"):
        RecoveryArenaTournamentReport.model_validate(
            {**report.model_dump(), "passed": not report.passed}
        )
