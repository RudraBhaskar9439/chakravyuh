"""Worker lifecycle tests."""

import asyncio
from unittest.mock import patch

from chakravyuh.worker.main import run, worker_main


async def test_worker_starts_and_stops_when_signalled() -> None:
    shutdown = asyncio.Event()
    shutdown.set()
    await worker_main(shutdown)


def test_worker_entrypoint() -> None:
    with patch("chakravyuh.worker.main.asyncio.run") as asyncio_run:
        run()

    asyncio_run.assert_called_once()
    asyncio_run.call_args.args[0].close()
