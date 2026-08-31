"""Build the sealed Recovery Arena v2 failed-payment report."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from chakravyuh.simulation.payment_link_arena import run_payment_link_arena


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--seed-count", type=int, default=667)
    parser.add_argument("--output", type=Path)
    return parser


async def _run(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    report = await run_payment_link_arena(
        code_revision=args.code_revision,
        seed_count=args.seed_count,
    )
    body = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(body)
    else:
        if args.output.exists():
            raise FileExistsError(f"output already exists: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    return 0 if report.passed else 1


def main(arguments: list[str] | None = None) -> int:
    return asyncio.run(_run(arguments))


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
