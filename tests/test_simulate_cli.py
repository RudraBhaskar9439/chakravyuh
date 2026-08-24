"""Offline simulation command tests."""

import argparse
import json
from unittest.mock import patch

import pytest

from chakravyuh.operations import simulate
from chakravyuh.simulation.journeys import JourneyScenario


def test_simulation_emits_machine_readable_evidence(capsys) -> None:  # type: ignore[no-untyped-def]
    exit_code = simulate.main(
        ["--scenario", JourneyScenario.PARTIALLY_REFUNDED.value, "--seed", "41"]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["scenario"] == JourneyScenario.PARTIALLY_REFUNDED.value
    assert output["expected_payment_status"] == "partially_refunded"
    assert len(output["state_hash"]) == 64
    assert output["reduced_state"]["event_count"] == 5


def test_simulation_rejects_invalid_seed_without_traceback(capsys) -> None:  # type: ignore[no-untyped-def]
    args = argparse.Namespace(
        scenario=JourneyScenario.SUCCESSFUL_PAYMENT.value,
        seed=-1,
        merchant_id="merchant-simulator",
    )

    assert simulate.simulation_main(args) == 2
    assert "non-negative" in capsys.readouterr().err


def test_simulation_parser_rejects_unknown_scenario() -> None:
    with pytest.raises(SystemExit):
        simulate._parser().parse_args(["--scenario", "unknown"])


def test_simulation_console_script_exits_with_command_status() -> None:
    with (
        patch("chakravyuh.operations.simulate.main", return_value=2),
        pytest.raises(SystemExit, match="2"),
    ):
        simulate.run()
