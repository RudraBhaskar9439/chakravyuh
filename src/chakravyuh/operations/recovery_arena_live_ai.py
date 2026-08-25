"""Prepare or explicitly execute the budgeted Recovery Arena live-AI sample."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from chakravyuh.config import Settings
from chakravyuh.domain.recovery_arena import create_recovery_arena_contract
from chakravyuh.infrastructure.openrouter.diagnostician import (
    OpenRouterStructuredDiagnostician,
)
from chakravyuh.simulation.live_ai_arena import (
    ArenaLiveAiReport,
    build_live_ai_sample,
    create_live_ai_run_contract,
    run_live_ai_arena,
)
from chakravyuh.simulation.recovery_portfolio import generate_held_out_recovery_portfolio

_ACKNOWLEDGED_MAX_COST_USD = Decimal("1.00")
_DEFAULT_CHECKPOINT = Path(".data/recovery-arena/live-ai-v1.jsonl")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare the precommitted 100-case live-AI experiment, or execute it with an "
            "explicit one-dollar acknowledgement."
        )
    )
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="send the precommitted sample to OpenRouter; omitted means prepare only",
    )
    parser.add_argument(
        "--acknowledge-max-cost-usd",
        help="required with --execute-live and must equal 1.00",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=_DEFAULT_CHECKPOINT,
        help="secret-free resumable JSONL checkpoint (default: %(default)s)",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    contract = create_recovery_arena_contract()
    portfolio = generate_held_out_recovery_portfolio(contract)
    sample = build_live_ai_sample(portfolio, contract)
    run_contract = create_live_ai_run_contract(
        sample,
        contract,
        requested_model=settings.openrouter_model,
    )
    if not args.execute_live:
        _print_result(
            sample_manifest=sample.manifest.model_dump(mode="json"),
            run_contract=run_contract.model_dump(mode="json"),
            live_execution=False,
        )
        return 0
    if settings.openrouter_api_key is None:
        msg = "CHAKRAVYUH_OPENROUTER_API_KEY is required for live execution"
        raise RuntimeError(msg)
    diagnostician = OpenRouterStructuredDiagnostician(
        settings,
        max_tokens=run_contract.max_output_tokens,
        provider_max_price={
            "prompt": run_contract.max_prompt_price_per_million_usd,
            "completion": run_contract.max_completion_price_per_million_usd,
        },
    )
    try:
        report, _ = await run_live_ai_arena(
            sample,
            run_contract,
            diagnostician,
            checkpoint_path=args.checkpoint,
            progress=_progress,
        )
    finally:
        await diagnostician.close()
    _print_result(
        sample_manifest=sample.manifest.model_dump(mode="json"),
        run_contract=run_contract.model_dump(mode="json"),
        live_execution=True,
        report=report,
    )
    return 0 if report.passed else 1


def _progress(completed: int, total: int, spent_microusd: int) -> None:
    if completed == total or completed % 5 == 0:
        sys.stderr.write(
            f"live-AI progress: {completed}/{total}; accounted cost: "
            f"${spent_microusd / 1_000_000:.6f}\n"
        )
        sys.stderr.flush()


def _print_result(
    *,
    sample_manifest: dict[str, object],
    run_contract: dict[str, object],
    live_execution: bool,
    report: ArenaLiveAiReport | None = None,
) -> None:
    payload: dict[str, object] = {
        "live_execution": live_execution,
        "sample_manifest": sample_manifest,
        "run_contract": run_contract,
    }
    if report is not None:
        payload["report"] = report.model_dump(mode="json")
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.execute_live:
        try:
            acknowledged = Decimal(args.acknowledge_max_cost_usd or "")
        except InvalidOperation:
            acknowledged = None
        if acknowledged != _ACKNOWLEDGED_MAX_COST_USD:
            parser.error("--execute-live requires --acknowledge-max-cost-usd 1.00")
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":  # pragma: no cover
    main()
