"""Audited CLI for rebuilding one completed or dead-lettered journey."""

import argparse
import asyncio
from collections.abc import Sequence

import structlog

from chakravyuh.application.journey_reduction import RequestJourneyReductionReplay
from chakravyuh.config import Settings, get_settings
from chakravyuh.domain.errors import JourneyReductionReplayNotAllowedError
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.journey_reduction_repository import (
    PostgresJourneyReductionRepository,
)
from chakravyuh.logging import configure_logging

logger = structlog.get_logger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild one completed or dead-lettered temporal payment journey.",
    )
    parser.add_argument("merchant_id", help="Bounded merchant identity")
    parser.add_argument("correlation_id", help="Payment-journey correlation identity")
    parser.add_argument("--requested-by", required=True, help="Auditable operator identity")
    parser.add_argument("--reason", required=True, help="Reason this rebuild is safe and necessary")
    return parser


async def replay_main(args: argparse.Namespace, *, settings: Settings | None = None) -> int:
    runtime_settings = settings or get_settings()
    configure_logging(
        runtime_settings.log_level,
        json_logs=runtime_settings.environment != "local",
    )
    database = Database(runtime_settings)
    try:
        replay = RequestJourneyReductionReplay(PostgresJourneyReductionRepository(database))
        replay_id = await replay.execute(
            args.merchant_id,
            args.correlation_id,
            requested_by=args.requested_by,
            reason=args.reason,
        )
    except (JourneyReductionReplayNotAllowedError, ValueError) as failure:
        await logger.aerror(
            "journey_replay_rejected",
            merchant_id=args.merchant_id,
            correlation_id=args.correlation_id,
            error_type=type(failure).__name__,
        )
        return 2
    finally:
        await database.close()

    await logger.ainfo(
        "journey_replay_queued",
        merchant_id=args.merchant_id,
        correlation_id=args.correlation_id,
        replay_id=str(replay_id),
        requested_by=args.requested_by,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(replay_main(_parser().parse_args(argv)))


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
