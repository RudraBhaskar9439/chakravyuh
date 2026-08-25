"""Audited CLI for replaying one dead-lettered grounded diagnosis."""

import argparse
import asyncio
from collections.abc import Sequence
from uuid import UUID

import structlog

from chakravyuh.application.diagnosis import RequestDiagnosisReplay
from chakravyuh.config import Settings, get_settings
from chakravyuh.domain.errors import DiagnosisReplayNotAllowedError
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.diagnosis_repository import PostgresDiagnosisRepository
from chakravyuh.logging import configure_logging

logger = structlog.get_logger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Return one dead-lettered diagnosis to its grounded AI queue.",
    )
    parser.add_argument("incident_id", type=UUID, help="Internal incident UUID")
    parser.add_argument("--requested-by", required=True, help="Auditable operator identity")
    parser.add_argument("--reason", required=True, help="Reason this replay is safe and necessary")
    return parser


async def replay_main(args: argparse.Namespace, *, settings: Settings | None = None) -> int:
    runtime_settings = settings or get_settings()
    configure_logging(
        runtime_settings.log_level,
        json_logs=runtime_settings.environment != "local",
    )
    database = Database(runtime_settings)
    try:
        replay = RequestDiagnosisReplay(PostgresDiagnosisRepository(database))
        replay_id = await replay.execute(
            args.incident_id,
            requested_by=args.requested_by,
            reason=args.reason,
        )
    except (DiagnosisReplayNotAllowedError, ValueError) as failure:
        await logger.aerror(
            "diagnosis_replay_rejected",
            incident_id=str(args.incident_id),
            error_type=type(failure).__name__,
        )
        return 2
    finally:
        await database.close()

    await logger.ainfo(
        "diagnosis_replay_queued",
        incident_id=str(args.incident_id),
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
