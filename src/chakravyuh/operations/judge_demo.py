"""One-command, machine-readable reliability and safety proof for judges."""

import argparse
import json
import sys
from collections.abc import Sequence

from chakravyuh.simulation.reliability import run_reliability_evaluation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run held-out correctness, chaos, policy, and latency proof gates.",
    )
    parser.add_argument("--seed-start", type=int, default=50_000)
    parser.add_argument("--seed-count", type=int, default=100)
    parser.add_argument("--latency-budget-ms", type=float, default=50)
    parser.add_argument("--minimum-cases-per-second", type=float, default=100)
    return parser


def judge_demo_main(args: argparse.Namespace) -> int:
    try:
        report = run_reliability_evaluation(
            seed_start=args.seed_start,
            seed_count=args.seed_count,
            latency_budget_ms=args.latency_budget_ms,
            minimum_cases_per_second=args.minimum_cases_per_second,
        )
    except ValueError as failure:
        sys.stderr.write(f"judge proof rejected: {failure}\n")
        return 2
    sys.stdout.write(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    sys.stdout.write("\n")
    return 0 if report.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    return judge_demo_main(_parser().parse_args(argv))


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
