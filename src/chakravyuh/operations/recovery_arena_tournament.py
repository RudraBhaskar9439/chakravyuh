"""Run the locked three-way Recovery Arena tournament."""

import asyncio
import json
import sys

from chakravyuh.domain.recovery_arena import create_recovery_arena_contract
from chakravyuh.simulation.recovery_portfolio import generate_held_out_recovery_portfolio
from chakravyuh.simulation.recovery_tournament import run_recovery_tournament


async def _run() -> int:
    contract = create_recovery_arena_contract()
    portfolio = generate_held_out_recovery_portfolio(contract)
    report, _, baseline = await run_recovery_tournament(portfolio, contract)
    sys.stdout.write(
        json.dumps(
            {
                "baseline_report": baseline.model_dump(mode="json"),
                "portfolio_manifest": portfolio.manifest.model_dump(mode="json"),
                "tournament_report": report.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    sys.stdout.write("\n")
    return 0 if report.passed else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":  # pragma: no cover
    main()
