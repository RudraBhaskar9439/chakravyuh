"""Judge-demo command contract tests."""

import json

from chakravyuh.operations.judge_demo import main


def test_judge_demo_outputs_machine_readable_passing_proof(capsys) -> None:  # type: ignore[no-untyped-def]
    status = main(
        [
            "--seed-start",
            "72000",
            "--seed-count",
            "1",
            "--latency-budget-ms",
            "1000",
            "--minimum-cases-per-second",
            "0.001",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert status == 0
    assert output["passed"] is True
    assert output["proof_sha256"]


def test_judge_demo_distinguishes_failed_gate_and_invalid_input(capsys) -> None:  # type: ignore[no-untyped-def]
    failed = main(["--seed-count", "1", "--minimum-cases-per-second", "1e100"])
    invalid = main(["--seed-count", "0"])
    captured = capsys.readouterr()

    assert failed == 1
    assert invalid == 2
    assert "judge proof rejected" in captured.err
