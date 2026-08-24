"""Offline CLI for emitting a deterministic journey and its reduced truth."""

import argparse
import json
import sys
from collections.abc import Sequence

from chakravyuh.domain.journeys import journey_state_hash, reduce_payment_journey
from chakravyuh.simulation.journeys import JourneyScenario, generate_synthetic_journey


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and reduce a deterministic synthetic payment journey.",
    )
    parser.add_argument(
        "--scenario",
        choices=[scenario.value for scenario in JourneyScenario],
        default=JourneyScenario.SUCCESSFUL_PAYMENT.value,
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--merchant-id", default="merchant-simulator")
    return parser


def simulation_main(args: argparse.Namespace) -> int:
    try:
        journey = generate_synthetic_journey(
            JourneyScenario(args.scenario),
            seed=args.seed,
            merchant_id=args.merchant_id,
        )
    except ValueError as failure:
        sys.stderr.write(f"simulation rejected: {failure}\n")
        return 2
    state = reduce_payment_journey(list(journey.events))
    result = {
        "scenario": journey.scenario.value,
        "seed": journey.seed,
        "expected_payment_status": journey.expected_payment_status.value,
        "state_hash": journey_state_hash(state),
        "delivery_events": [event.model_dump(mode="json") for event in journey.events],
        "reduced_state": state.model_dump(mode="json"),
    }
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    sys.stdout.write("\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return simulation_main(_parser().parse_args(argv))


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
