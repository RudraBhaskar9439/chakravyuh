"""Held-out fault-set metrics and CLI proofs."""

import argparse
import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from chakravyuh.domain.invariants import DeterministicPaymentInvariantEvaluator
from chakravyuh.operations import evaluate_invariants
from chakravyuh.simulation.faults import evaluate_fault_set, generate_fault_set


def test_held_out_fault_set_has_perfect_exact_label_metrics() -> None:
    cases = generate_fault_set(range(10_000, 10_020))

    metrics = evaluate_fault_set(cases, DeterministicPaymentInvariantEvaluator())

    assert metrics.case_count == 300
    assert metrics.expected_finding_count == 120
    assert metrics.predicted_finding_count == 120
    assert metrics.true_positive_count == 120
    assert metrics.false_positive_count == 0
    assert metrics.false_negative_count == 0
    assert metrics.precision == metrics.recall == metrics.f1 == 1
    assert metrics.false_positive_review_cost_subunits == 0
    assert metrics.dataset_role == "held_out_synthetic"
    assert metrics.decision_authority == "deterministic_rules_only"


def test_false_positive_cost_is_counted_honestly() -> None:
    positive = generate_fault_set([20_000])[0]
    incorrectly_labelled_negative = replace(positive, expected_labels=frozenset())

    metrics = evaluate_fault_set(
        [incorrectly_labelled_negative],
        DeterministicPaymentInvariantEvaluator(),
    )

    assert metrics.false_positive_count == 1
    assert metrics.precision == 0
    assert metrics.false_positive_review_cost_subunits == 2_000


@pytest.mark.parametrize("seeds", [[], [-1], [1, 1]])
def test_fault_set_rejects_invalid_seed_sets(seeds: list[int]) -> None:
    with pytest.raises(ValueError):
        generate_fault_set(seeds)


def test_metrics_reject_empty_cases_and_negative_cost() -> None:
    evaluator = DeterministicPaymentInvariantEvaluator()
    with pytest.raises(ValueError, match="at least one"):
        evaluate_fault_set([], evaluator)
    with pytest.raises(ValueError, match="non-negative"):
        evaluate_fault_set(
            generate_fault_set([1]),
            evaluator,
            false_positive_review_cost_subunits=-1,
        )


def test_evaluation_cli_emits_machine_readable_proof(capsys) -> None:  # type: ignore[no-untyped-def]
    exit_code = evaluate_invariants.main(["--seed-start", "30000", "--seed-count", "2"])

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["metrics"]["case_count"] == 30
    assert result["metrics"]["precision"] == 1
    assert result["metrics"]["recall"] == 1


def test_evaluation_cli_rejects_unbounded_request(capsys) -> None:  # type: ignore[no-untyped-def]
    args = argparse.Namespace(seed_start=-1, seed_count=0)

    assert evaluate_invariants.evaluation_main(args) == 2
    assert "evaluation rejected" in capsys.readouterr().err


def test_evaluation_entrypoint() -> None:
    with (
        patch("chakravyuh.operations.evaluate_invariants.main", return_value=2),
        pytest.raises(SystemExit, match="2"),
    ):
        evaluate_invariants.run()
