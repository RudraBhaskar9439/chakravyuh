"""Audited CLI for re-enqueuing every authoritative journey graph projection."""

import argparse
import asyncio
from collections.abc import Sequence

import structlog

from chakravyuh.config import Settings, get_settings
from chakravyuh.domain.errors import GraphRebuildNotAllowedError
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.graph_projection_repository import (
    PostgresGraphProjectionRepository,
)
from chakravyuh.logging import configure_logging

logger = structlog.get_logger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-enqueue every PostgreSQL journey for idempotent graph reconstruction.",
    )
    parser.add_argument("--requested-by", required=True, help="Auditable operator identity")
    parser.add_argument("--reason", required=True, help="Reason a complete rebuild is required")
    return parser


async def rebuild_main(args: argparse.Namespace, *, settings: Settings | None = None) -> int:
    runtime_settings = settings or get_settings()
    configure_logging(
        runtime_settings.log_level,
        json_logs=runtime_settings.environment != "local",
    )
    database = Database(runtime_settings)
    try:
        rebuild_id, journey_count = await PostgresGraphProjectionRepository(
            database
        ).request_rebuild(
            requested_by=args.requested_by,
            reason=args.reason,
        )
    except (GraphRebuildNotAllowedError, ValueError) as failure:
        await logger.aerror(
            "graph_rebuild_rejected",
            error_type=type(failure).__name__,
        )
        return 2
    finally:
        await database.close()
    await logger.ainfo(
        "graph_rebuild_queued",
        rebuild_id=str(rebuild_id),
        journey_count=journey_count,
        requested_by=args.requested_by,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(rebuild_main(_parser().parse_args(argv)))


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
