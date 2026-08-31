"""Build the sealed Recovery Arena v2 failed-payment report."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from chakravyuh.simulation.payment_link_arena import (
    PaymentLinkArenaReport,
    run_payment_link_arena,
)


class PaymentLinkArenaVerificationError(ValueError):
    """The report differs from its trust anchors or deterministic replay."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-revision")
    parser.add_argument("--seed-count", type=int, default=667)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--expected-code-revision")
    parser.add_argument("--expected-report-sha256")
    return parser


async def _run(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    if args.verify is not None:
        if args.output is not None or args.code_revision is not None:
            raise ValueError("verification cannot be combined with build arguments")
        await verify_payment_link_arena_report(
            args.verify,
            expected_code_revision=args.expected_code_revision,
            expected_report_sha256=args.expected_report_sha256,
        )
        return 0
    if args.code_revision is None:
        raise ValueError("--code-revision is required when building a report")
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


async def verify_payment_link_arena_report(
    path: Path,
    *,
    expected_code_revision: str | None = None,
    expected_report_sha256: str | None = None,
) -> PaymentLinkArenaReport:
    body = await asyncio.to_thread(path.read_text, encoding="utf-8")
    report = PaymentLinkArenaReport.model_validate_json(body)
    if expected_code_revision is not None and report.code_revision != expected_code_revision:
        raise PaymentLinkArenaVerificationError("report has a different code revision")
    if expected_report_sha256 is not None and report.report_sha256 != expected_report_sha256:
        raise PaymentLinkArenaVerificationError("report does not match the trusted SHA-256")
    case_count = report.strategies[0].case_count
    if case_count % 15:
        raise PaymentLinkArenaVerificationError("report case count is outside generator bounds")
    replay = await run_payment_link_arena(
        code_revision=report.code_revision,
        seed_count=case_count // 15,
    )
    if replay != report:
        raise PaymentLinkArenaVerificationError("report differs from deterministic replay")
    return report


def main(arguments: list[str] | None = None) -> int:
    return asyncio.run(_run(arguments))


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
