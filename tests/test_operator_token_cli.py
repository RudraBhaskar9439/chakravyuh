"""Operator credential issuance tests."""

import argparse
import hashlib
import json
from unittest.mock import patch

import pytest

from chakravyuh.operations import operator_token


def test_operator_credential_is_high_entropy_and_configures_only_its_hash() -> None:
    credential = operator_token.issue_operator_credential("incident-reviewer")

    assert len(credential.operator_token) >= 43
    assert credential.sha256 == hashlib.sha256(credential.operator_token.encode()).hexdigest()
    assert json.loads(credential.environment_value) == {
        "incident-reviewer": credential.sha256,
    }
    assert credential.operator_token not in credential.environment_value


@pytest.mark.parametrize("principal", ["", " " * 3, "x" * 65])
def test_operator_credential_rejects_unsafe_principals(principal: str) -> None:
    with pytest.raises(ValueError, match="between 1 and 64"):
        operator_token.issue_operator_credential(principal)


def test_operator_token_command_emits_one_time_machine_readable_credential(capsys) -> None:  # type: ignore[no-untyped-def]
    assert operator_token.main(["--principal", "local-reviewer"]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["principal_id"] == "local-reviewer"
    assert output["operator_token"]
    assert output["operator_token"] not in output["environment_value"]
    assert "password manager" in captured.err


def test_operator_token_command_rejects_invalid_input_without_a_traceback(capsys) -> None:  # type: ignore[no-untyped-def]
    assert operator_token.operator_token_main(argparse.Namespace(principal="")) == 2
    assert "operator credential rejected" in capsys.readouterr().err


def test_operator_token_console_script_exits_with_command_status() -> None:
    with (
        patch("chakravyuh.operations.operator_token.main", return_value=2),
        pytest.raises(SystemExit, match="2"),
    ):
        operator_token.run()
