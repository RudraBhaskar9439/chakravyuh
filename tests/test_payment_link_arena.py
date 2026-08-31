"""Recovery Arena v2 failed-payment safety and evidence tests."""

import json
from pathlib import Path

import pytest

from chakravyuh.domain.enums import ActionType, IncidentType
from chakravyuh.operations import payment_link_arena as arena_cli
from chakravyuh.simulation.payment_link_arena import (
    PaymentLinkFault,
    PaymentLinkStrategyName,
    create_payment_link_arena_contract,
    run_payment_link_arena,
)

_REVISION = "a" * 40


def test_v2_contract_is_separate_locked_and_content_addressed() -> None:
    contract = create_payment_link_arena_contract()

    assert contract.recoverable_incident is IncidentType.FAILED_WITHOUT_RECOVERY
    assert contract.executable_action is ActionType.CREATE_PAYMENT_LINK
    assert contract.confirmation_event == "payment_link.paid"
    assert contract.held_out_case_count == 10_005
    assert contract.strategies == tuple(PaymentLinkStrategyName)
    assert contract.fault_scenarios == tuple(PaymentLinkFault)
    assert contract.contract_sha256 == (
        "6a05b77743d48a2d8ea1d2396a157083f9b844093fa84d282f96f309c132e933"
    )


async def test_small_v2_tournament_is_reproducible_and_fail_safe() -> None:
    first = await run_payment_link_arena(code_revision=_REVISION, seed_count=10)
    second = await run_payment_link_arena(code_revision=_REVISION, seed_count=10)
    no_action, blind, guarded = first.strategies

    assert first == second
    assert first.passed
    assert guarded.detection_precision == guarded.detection_recall == 1.0
    assert guarded.action_precision == guarded.action_recall == 1.0
    assert guarded.incorrect_action_count == guarded.duplicate_link_creation_count == 0
    assert guarded.confirmed_recovery_count == blind.confirmed_recovery_count
    assert guarded.net_recovery_value_subunits > no_action.net_recovery_value_subunits
    assert guarded.net_recovery_value_subunits > blind.net_recovery_value_subunits


async def test_full_v2_tournament_has_stable_held_out_commitment() -> None:
    report = await run_payment_link_arena(code_revision=_REVISION)
    _, blind, guarded = report.strategies

    assert report.passed
    assert report.base_portfolio_manifest_sha256 == (
        "00a7a5e66c1dc203a06548adaf186db5931ada9d9d1eb3a47ed8b733b2d27112"
    )
    assert report.oracle_root_sha256 == (
        "5a10b39697e69f52769f25ddce9891ad22054b99911d41ca99d1a4de307579a8"
    )
    assert guarded.action_eligible_count == guarded.action_attempt_count == 577
    assert guarded.confirmed_recovery_count == blind.confirmed_recovery_count == 203
    assert guarded.confirmation_delivery_count == 265
    assert guarded.unique_confirmation_count == 203
    assert guarded.net_recovery_value_subunits == 5_167_000
    assert blind.incorrect_action_count == 757
    assert report.report_sha256 == (
        "0148f1d1e0dbf43e6732c2be1d7e9788351799e1dbac13c827ef0dc569fa2796"
    )


def test_cli_writes_once_and_rejects_bad_revision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "report.json"

    assert (
        arena_cli.main(
            ["--code-revision", _REVISION, "--seed-count", "10", "--output", str(output)]
        )
        == 0
    )
    assert json.loads(output.read_text())["passed"] is True
    with pytest.raises(FileExistsError, match="already exists"):
        arena_cli.main(
            ["--code-revision", _REVISION, "--seed-count", "10", "--output", str(output)]
        )
    with pytest.raises(ValueError, match="40-character Git SHA"):
        arena_cli.main(["--code-revision", "short", "--seed-count", "10"])
    assert capsys.readouterr().out == ""
