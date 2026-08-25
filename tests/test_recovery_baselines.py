"""Counterfactual baseline behavior and honest economic scoring tests."""

import json

import pytest
from pydantic import ValidationError

from chakravyuh.domain.recovery_arena import (
    ArenaDatasetRole,
    ArenaStrategyName,
    RecoveryArenaContract,
    create_recovery_arena_contract,
)
from chakravyuh.operations import recovery_arena_baselines as baseline_cli
from chakravyuh.simulation.razorpay_twin import DeterministicRazorpayTwin
from chakravyuh.simulation.recovery_baselines import (
    ArenaBaselineReport,
    NoInterventionStrategy,
    RetryAllStrategy,
    run_baseline_tournament,
)
from chakravyuh.simulation.recovery_portfolio import (
    RecoveryPortfolio,
    generate_held_out_recovery_portfolio,
    generate_recovery_portfolio,
)


def _portfolio(seed_count: int = 10) -> tuple[RecoveryArenaContract, RecoveryPortfolio]:
    contract = create_recovery_arena_contract()
    portfolio = generate_recovery_portfolio(
        contract,
        dataset_role=ArenaDatasetRole.VALIDATION,
        seed_start=40_000,
        seed_count=seed_count,
    )
    return contract, portfolio


async def test_baseline_tournament_compares_same_cases_and_exposes_retry_all_cost() -> None:
    contract, portfolio = _portfolio()

    report, results = await run_baseline_tournament(portfolio, contract)
    no_action, retry_all = report.strategies

    assert report.passed
    assert no_action.strategy is ArenaStrategyName.NO_INTERVENTION
    assert no_action.case_count == retry_all.case_count == 150
    assert no_action.action_attempt_count == no_action.confirmed_recovery_count == 0
    assert no_action.missed_recoverable_count == no_action.oracle_recoverable_count
    assert retry_all.action_attempt_count > 0
    assert retry_all.confirmed_recovery_count > 0
    assert retry_all.incorrect_action_count > 0
    assert retry_all.incorrect_action_cost_subunits > 0
    assert retry_all.duplicate_mutation_count == 0
    assert len(results) == 300
    assert len({(item.strategy, item.case_id) for item in results}) == 300


async def test_baseline_report_and_result_roots_are_reproducible() -> None:
    contract, portfolio = _portfolio(seed_count=2)

    first, first_results = await run_baseline_tournament(portfolio, contract)
    second, second_results = await run_baseline_tournament(portfolio, contract)

    assert first == second
    assert first_results == second_results


async def test_locked_held_out_baseline_has_stable_economic_commitment() -> None:
    contract = create_recovery_arena_contract()
    portfolio = generate_held_out_recovery_portfolio(contract)

    report, _ = await run_baseline_tournament(portfolio, contract)
    no_action, retry_all = report.strategies

    assert report.report_sha256 == (
        "d58a681121480d489a3e30eb4b1ca86a37cb864ef2a94ede23dc35abcf32c2c9"
    )
    assert no_action.missed_recoverable_count == 421
    assert retry_all.confirmed_recovery_count == 402
    assert retry_all.incorrect_action_count == 3_545
    assert retry_all.net_recovery_value_subunits == -19_722_000


async def test_baseline_cli_emits_manifest_and_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, portfolio = _portfolio(seed_count=1)
    monkeypatch.setattr(
        baseline_cli,
        "generate_held_out_recovery_portfolio",
        lambda _: portfolio,
    )

    assert await baseline_cli._run() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["portfolio_manifest"]["case_count"] == 15
    assert output["baseline_report"]["passed"] is True


async def test_strategies_receive_only_observed_case_and_narrow_gateway() -> None:
    _, portfolio = _portfolio(seed_count=1)
    case = portfolio.cases[0]
    twin = DeterministicRazorpayTwin(case.oracle.provider_plan)

    no_action = await NoInterventionStrategy().run(case.observed, twin.strategy_gateway())
    retry_all = await RetryAllStrategy().run(case.observed, twin.strategy_gateway())

    assert no_action.case_id == retry_all.case_id == case.observed.case_id
    observed_document = json.loads(case.observed.model_dump_json())
    assert "oracle" not in observed_document
    assert "family" not in observed_document
    assert "seed" not in observed_document


async def test_baseline_report_rejects_tampering() -> None:
    contract, portfolio = _portfolio(seed_count=1)
    report, _ = await run_baseline_tournament(portfolio, contract)

    with pytest.raises(ValidationError, match="report hash"):
        ArenaBaselineReport.model_validate({**report.model_dump(), "report_sha256": "f" * 64})
    with pytest.raises(ValidationError, match="pass flag"):
        ArenaBaselineReport.model_validate({**report.model_dump(), "passed": False})
    with pytest.raises(ValidationError, match="canonical"):
        ArenaBaselineReport.model_validate(
            {**report.model_dump(), "strategies": tuple(reversed(report.strategies))}
        )
