"""Worker lifecycle; queue consumers are introduced with event ingestion."""

import asyncio

import structlog

from chakravyuh import __version__
from chakravyuh.config import get_settings
from chakravyuh.logging import configure_logging

logger = structlog.get_logger(__name__)


async def worker_main(shutdown_event: asyncio.Event | None = None) -> None:
    """Run until the process receives a shutdown signal from its host."""
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.environment != "local")
    event = shutdown_event or asyncio.Event()
    await logger.ainfo(
        "worker_started",
        environment=settings.environment,
        version=__version__,
    )
    await event.wait()
    await logger.ainfo("worker_stopped")


def run() -> None:
    """Run the asynchronous worker process."""
    asyncio.run(worker_main())


if __name__ == "__main__":  # pragma: no cover
    run()
