"""Long-running durable normalization worker lifecycle."""

import asyncio
import os
import signal
import socket
from contextlib import suppress
from typing import Protocol

import structlog

from chakravyuh import __version__
from chakravyuh.application.journey_reduction import ProcessJourneyReductionBatch
from chakravyuh.application.normalization import NormalizationBatchResult, ProcessNormalizationBatch
from chakravyuh.application.pipeline import PipelineBatchResult, ProcessPipelineBatch
from chakravyuh.config import Settings, get_settings
from chakravyuh.domain.journeys import TemporalPaymentJourneyReducer
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.journey_reduction_repository import (
    PostgresJourneyReductionRepository,
)
from chakravyuh.infrastructure.postgres.normalization_repository import (
    PostgresNormalizationRepository,
)
from chakravyuh.infrastructure.razorpay.normalizer import RazorpayWebhookNormalizer
from chakravyuh.logging import configure_logging

logger = structlog.get_logger(__name__)


class BatchProcessor(Protocol):
    async def execute(self) -> NormalizationBatchResult | PipelineBatchResult: ...


async def worker_main(
    shutdown_event: asyncio.Event | None = None,
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    processor: BatchProcessor | None = None,
) -> None:
    """Process committed batches until the host asks for graceful shutdown."""
    runtime_settings = settings or get_settings()
    configure_logging(
        runtime_settings.log_level,
        json_logs=runtime_settings.environment != "local",
    )
    event = shutdown_event or asyncio.Event()
    owned_database: Database | None = None
    if processor is None:
        runtime_database = database
        if runtime_database is None:
            runtime_database = Database(runtime_settings)
            owned_database = runtime_database
        worker_id = _worker_id()
        normalization = ProcessNormalizationBatch(
            PostgresNormalizationRepository(runtime_database),
            RazorpayWebhookNormalizer(),
            worker_id=worker_id,
            batch_size=runtime_settings.worker_batch_size,
        )
        journey_reduction = ProcessJourneyReductionBatch(
            PostgresJourneyReductionRepository(runtime_database),
            TemporalPaymentJourneyReducer(),
            worker_id=worker_id,
            batch_size=runtime_settings.journey_reduction_batch_size,
            max_events_per_journey=runtime_settings.journey_max_events,
        )
        processor = ProcessPipelineBatch(
            normalization,
            journey_reduction,
        )

    await logger.ainfo(
        "worker_started",
        environment=runtime_settings.environment,
        version=__version__,
        batch_size=runtime_settings.worker_batch_size,
        journey_batch_size=runtime_settings.journey_reduction_batch_size,
    )
    try:
        while not event.is_set():
            try:
                result = await processor.execute()
            except Exception as failure:
                await logger.aerror(
                    "pipeline_batch_failed",
                    error_type=type(failure).__name__,
                )
                await _wait_for_shutdown(event, runtime_settings.worker_error_backoff_seconds)
                continue

            if result.claimed == 0:
                await _wait_for_shutdown(event, runtime_settings.worker_poll_interval_seconds)
                continue
            await logger.ainfo(
                "pipeline_batch_committed",
                claimed=result.claimed,
                completed=result.completed,
                dead_lettered=result.dead_lettered,
            )
    finally:
        if owned_database is not None:
            await owned_database.close()
        await logger.ainfo("worker_stopped")


async def _wait_for_shutdown(event: asyncio.Event, delay_seconds: float) -> None:
    with suppress(TimeoutError):
        await asyncio.wait_for(event.wait(), timeout=delay_seconds)


def _worker_id() -> str:
    process_id = str(os.getpid())
    hostname = socket.gethostname()[: 254 - len(process_id)]
    return f"{hostname}:{process_id}"


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
        await worker_main(event)
    finally:
        for process_signal in installed:
            loop.remove_signal_handler(process_signal)


def run() -> None:
    """Run the worker with SIGINT and SIGTERM mapped to a graceful stop."""
    asyncio.run(_run_with_signals())


if __name__ == "__main__":  # pragma: no cover
    run()
