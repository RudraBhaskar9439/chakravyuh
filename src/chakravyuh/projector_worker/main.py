"""Long-running leased Neo4j projection worker lifecycle."""

import asyncio
import os
import signal
import socket
from typing import Protocol

import structlog

from chakravyuh import __version__
from chakravyuh.application.graph_projection import (
    GraphProjectionBatchResult,
    ProcessGraphProjectionBatch,
)
from chakravyuh.application.graph_rebuild import (
    FinalizeGraphRebuilds,
    GraphRebuildFinalizationResult,
)
from chakravyuh.application.ports import GraphProjector
from chakravyuh.config import Settings, get_settings
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.neo4j.projector import Neo4jPaymentGraphProjector
from chakravyuh.infrastructure.postgres.graph_projection_repository import (
    PostgresGraphProjectionRepository,
)
from chakravyuh.logging import configure_logging
from chakravyuh.worker.main import _wait_for_shutdown

logger = structlog.get_logger(__name__)


class BatchProcessor(Protocol):
    async def execute(self) -> GraphProjectionBatchResult: ...


class RebuildFinalizer(Protocol):
    async def execute(self) -> GraphRebuildFinalizationResult: ...


async def projector_worker_main(
    shutdown_event: asyncio.Event | None = None,
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    projector: GraphProjector | None = None,
    processor: BatchProcessor | None = None,
    finalizer: RebuildFinalizer | None = None,
) -> None:
    runtime_settings = settings or get_settings()
    configure_logging(
        runtime_settings.log_level,
        json_logs=runtime_settings.environment != "local",
    )
    event = shutdown_event or asyncio.Event()
    owned_database: Database | None = None
    owned_projector: GraphProjector | None = None
    if processor is None:
        runtime_database = database
        if runtime_database is None:
            runtime_database = Database(runtime_settings)
            owned_database = runtime_database
        runtime_projector = projector
        if runtime_projector is None:
            runtime_projector = Neo4jPaymentGraphProjector(runtime_settings)
            owned_projector = runtime_projector
        await runtime_projector.initialize_schema()
        repository = PostgresGraphProjectionRepository(runtime_database)
        processor = ProcessGraphProjectionBatch(
            repository,
            runtime_projector,
            worker_id=_worker_id(),
            batch_size=runtime_settings.graph_projection_batch_size,
            lease_seconds=runtime_settings.graph_projection_lease_seconds,
            max_failures=runtime_settings.graph_projection_max_failures,
            retry_delay_seconds=runtime_settings.graph_projection_retry_delay_seconds,
        )
        finalizer = FinalizeGraphRebuilds(repository, runtime_projector)

    await logger.ainfo(
        "projector_worker_started",
        environment=runtime_settings.environment,
        version=__version__,
        batch_size=runtime_settings.graph_projection_batch_size,
    )
    try:
        while not event.is_set():
            try:
                result = await processor.execute()
            except Exception as failure:
                await logger.aerror(
                    "projection_batch_failed",
                    error_type=type(failure).__name__,
                )
                await _wait_for_shutdown(event, runtime_settings.worker_error_backoff_seconds)
                continue
            if result.claimed:
                await logger.ainfo(
                    "projection_batch_committed",
                    claimed=result.claimed,
                    completed=result.completed,
                    retried=result.retried,
                    dead_lettered=result.dead_lettered,
                    lease_lost=result.lease_lost,
                )
            finalization = GraphRebuildFinalizationResult()
            if finalizer is not None:
                try:
                    finalization = await finalizer.execute()
                except Exception as failure:
                    await logger.aerror(
                        "graph_rebuild_finalization_failed",
                        error_type=type(failure).__name__,
                    )
                    await _wait_for_shutdown(event, runtime_settings.worker_error_backoff_seconds)
                    continue
                if finalization.completed:
                    await logger.ainfo(
                        "graph_rebuild_finalized",
                        candidates=finalization.candidates,
                        completed=finalization.completed,
                    )
            if result.claimed == 0 and finalization.candidates == 0:
                await _wait_for_shutdown(event, runtime_settings.worker_poll_interval_seconds)
    finally:
        if owned_projector is not None:
            await owned_projector.close()
        if owned_database is not None:
            await owned_database.close()
        await logger.ainfo("projector_worker_stopped")


def _worker_id() -> str:
    process_id = str(os.getpid())
    hostname = socket.gethostname()[: 248 - len(process_id)]
    return f"graph:{hostname}:{process_id}"


async def _run_with_signals() -> None:
    event = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for process_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(process_signal, event.set)
        except NotImplementedError:  # pragma: no cover - Windows event loop fallback
            continue
        installed.append(process_signal)
    try:
        await projector_worker_main(event)
    finally:
        for process_signal in installed:
            loop.remove_signal_handler(process_signal)


def run() -> None:
    asyncio.run(_run_with_signals())


if __name__ == "__main__":  # pragma: no cover
    run()
