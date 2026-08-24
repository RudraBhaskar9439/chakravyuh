"""Offline held-out evaluation CLI for the deterministic invariant engine."""

import argparse
import json
import sys
from collections.abc import Sequence

from chakravyuh.domain.invariants import DeterministicPaymentInvariantEvaluator, InvariantPolicy
from chakravyuh.simulation.faults import evaluate_fault_set, generate_fault_set


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure invariant precision, recall, and false-positive review cost.",
    )
    parser.add_argument("--seed-start", type=int, default=10_000)
    parser.add_argument("--seed-count", type=int, default=100)
    return parser


def evaluation_main(args: argparse.Namespace) -> int:
    if args.seed_start < 0 or args.seed_count < 1 or args.seed_count > 10_000:
        sys.stderr.write(
            "evaluation rejected: seed-start must be non-negative and seed-count must be 1..10000\n"
        )
        return 2
    cases = generate_fault_set(range(args.seed_start, args.seed_start + args.seed_count))
    evaluator = DeterministicPaymentInvariantEvaluator(InvariantPolicy())
    metrics = evaluate_fault_set(cases, evaluator)
    result = {
        "evaluator_version": evaluator.version,
        "seed_start": args.seed_start,
        "seed_count": args.seed_count,
        "metrics": metrics.model_dump(mode="json"),
    }
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    sys.stdout.write("\n")
    return 0 if metrics.false_positive_count == metrics.false_negative_count == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    return evaluation_main(_parser().parse_args(argv))


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
