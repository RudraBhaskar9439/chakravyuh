"""Low-memory hosted runtime for a single-container preview environment."""

import asyncio
import os

from uvicorn import Config, Server

from chakravyuh.config import Settings, get_settings
from chakravyuh.diagnosis_worker.main import diagnosis_worker_main
from chakravyuh.projector_worker.main import projector_worker_main
from chakravyuh.worker.main import worker_main


async def hosted_main(settings: Settings | None = None) -> None:
    """Run the API and all durable processors in one shared Python process.

    This topology is intended for constrained preview hosts. The regular
    production manifests continue to run each processor independently.
    """
    runtime_settings = settings or get_settings()
    shutdown_event = asyncio.Event()
    server = Server(
        Config(
            "chakravyuh.api.main:create_app",
            factory=True,
            host=runtime_settings.api_host,
            port=_hosted_port(runtime_settings),
            log_config=None,
        )
    )

    async def serve_api() -> None:
        try:
            await server.serve()
        finally:
            shutdown_event.set()

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(serve_api(), name="api")
        tasks.create_task(
            worker_main(shutdown_event, settings=runtime_settings),
            name="pipeline-worker",
        )
        tasks.create_task(
            projector_worker_main(shutdown_event, settings=runtime_settings),
            name="graph-projector",
        )
        tasks.create_task(
            diagnosis_worker_main(shutdown_event, settings=runtime_settings),
            name="diagnosis-worker",
        )


def _hosted_port(settings: Settings) -> int:
    supplied_port = os.getenv("PORT")
    if supplied_port is None:
        return settings.api_port
    try:
        port = int(supplied_port)
    except ValueError as failure:
        msg = "PORT must be an integer"
        raise ValueError(msg) from failure
    if not 1 <= port <= 65_535:
        msg = "PORT must be between 1 and 65535"
        raise ValueError(msg)
    return port


def run() -> None:
    """Start the single-container hosted runtime."""
    asyncio.run(hosted_main())


if __name__ == "__main__":  # pragma: no cover
    run()
