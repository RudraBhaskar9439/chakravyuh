"""Deterministic judge-proof pack tests."""

import pytest

from chakravyuh.simulation.reliability import run_reliability_evaluation


def test_reliability_pack_proves_correctness_chaos_policy_and_load() -> None:
    report = run_reliability_evaluation(
        seed_start=70_000,
        seed_count=3,
        latency_budget_ms=1_000,
        minimum_cases_per_second=0.001,
    )

    assert report.passed
    assert report.invariant_metrics.case_count == 45
    assert report.invariant_metrics.false_positive_count == 0
    assert report.invariant_metrics.false_negative_count == 0
    assert all(check.passed for check in report.chaos_checks)
    assert all(check.passed for check in report.recovery_policy_checks)
    assert len(report.proof_sha256) == 64


def test_reliability_proof_digest_excludes_wall_clock_and_timing() -> None:
    first = run_reliability_evaluation(seed_start=71_000, seed_count=1)
    second = run_reliability_evaluation(seed_start=71_000, seed_count=1)

    assert first.generated_at != second.generated_at
    assert first.load_metrics != second.load_metrics
    assert first.proof_sha256 == second.proof_sha256


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({"seed_start": -1}, "seed_start"),
        ({"seed_count": 0}, "seed_count"),
        ({"seed_count": 10_001}, "seed_count"),
        ({"latency_budget_ms": 0}, "SLO"),
        ({"minimum_cases_per_second": 0}, "SLO"),
    ],
)
def test_reliability_pack_rejects_unbounded_inputs(
    parameters: dict[str, int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        run_reliability_evaluation(**parameters)
