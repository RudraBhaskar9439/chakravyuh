"""Long-running isolated worker for evidence-grounded model diagnosis."""

import asyncio
import os
import signal
import socket
from typing import Protocol

import structlog

from chakravyuh import __version__
from chakravyuh.application.diagnosis import DiagnosisBatchResult, ProcessDiagnosisBatch
from chakravyuh.application.evidence_assembly import AssembleEvidenceSubgraph
from chakravyuh.application.ports import StructuredDiagnostician
from chakravyuh.config import Settings, get_settings
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.diagnosis.factory import build_structured_diagnostician
from chakravyuh.infrastructure.neo4j.evidence_reader import Neo4jEvidenceReader
from chakravyuh.infrastructure.postgres.diagnosis_repository import (
    PostgresDiagnosisRepository,
)
from chakravyuh.logging import configure_logging
from chakravyuh.worker.main import _wait_for_shutdown

logger = structlog.get_logger(__name__)


class BatchProcessor(Protocol):
    async def execute(self) -> DiagnosisBatchResult: ...


async def diagnosis_worker_main(
    shutdown_event: asyncio.Event | None = None,
    *,
    settings: Settings | None = None,
    processor: BatchProcessor | None = None,
) -> None:
    runtime_settings = settings or get_settings()
    configure_logging(
        runtime_settings.log_level,
        json_logs=runtime_settings.environment != "local",
    )
    event = shutdown_event or asyncio.Event()
    database: Database | None = None
    reader: Neo4jEvidenceReader | None = None
    diagnostician: StructuredDiagnostician | None = None
    if processor is None:
        diagnostician = build_structured_diagnostician(runtime_settings)
        try:
            database = Database(runtime_settings)
            reader = Neo4jEvidenceReader(runtime_settings)
        except Exception:
            if reader is not None:
                await reader.close()
            if database is not None:
                await database.close()
            await diagnostician.close()
            raise
        repository = PostgresDiagnosisRepository(database)
        assembler = AssembleEvidenceSubgraph(
            reader,
            max_facts=runtime_settings.diagnosis_max_facts,
            max_relationships=runtime_settings.diagnosis_max_relationships,
        )
        processor = ProcessDiagnosisBatch(
            repository,
            assembler,
            diagnostician,
            worker_id=_worker_id(),
            batch_size=runtime_settings.diagnosis_batch_size,
            lease_seconds=runtime_settings.diagnosis_lease_seconds,
            max_failures=runtime_settings.diagnosis_max_failures,
            retry_delay_seconds=runtime_settings.diagnosis_retry_delay_seconds,
        )

    await logger.ainfo(
        "diagnosis_worker_started",
        environment=runtime_settings.environment,
        version=__version__,
        batch_size=runtime_settings.diagnosis_batch_size,
        diagnosis_primary_provider=runtime_settings.diagnosis_primary_provider,
        diagnosis_fallback_provider=runtime_settings.diagnosis_fallback_provider,
    )
    try:
        while not event.is_set():
            try:
                result = await processor.execute()
            except Exception as failure:
                await logger.aerror(
                    "diagnosis_batch_failed",
                    error_type=type(failure).__name__,
                )
                await _wait_for_shutdown(event, runtime_settings.worker_error_backoff_seconds)
                continue
            if result.claimed:
                await logger.ainfo(
                    "diagnosis_batch_committed",
                    claimed=result.claimed,
                    completed=result.completed,
                    retried=result.retried,
                    dead_lettered=result.dead_lettered,
                    lease_lost=result.lease_lost,
                )
            else:
                await _wait_for_shutdown(event, runtime_settings.worker_poll_interval_seconds)
    finally:
        if diagnostician is not None:
            await diagnostician.close()
        if reader is not None:
            await reader.close()
        if database is not None:
            await database.close()
        await logger.ainfo("diagnosis_worker_stopped")


def _worker_id() -> str:
    process_id = str(os.getpid())
    hostname = socket.gethostname()[: 247 - len(process_id)]
    return f"diagnosis:{hostname}:{process_id}"


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
        await diagnosis_worker_main(event)
    finally:
        for process_signal in installed:
            loop.remove_signal_handler(process_signal)


def run() -> None:
    asyncio.run(_run_with_signals())


if __name__ == "__main__":  # pragma: no cover
    run()
