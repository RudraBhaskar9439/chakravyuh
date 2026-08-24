"""Normalization worker lifecycle tests."""

import asyncio
from unittest.mock import AsyncMock, patch

from chakravyuh.application.normalization import NormalizationBatchResult
from chakravyuh.config import Settings
from chakravyuh.worker.main import (
    _run_with_signals,
    _wait_for_shutdown,
    _worker_id,
    run,
    worker_main,
)


class StoppingProcessor:
    def __init__(
        self,
        shutdown: asyncio.Event,
        *,
        failure: Exception | None = None,
    ) -> None:
        self.shutdown = shutdown
        self.failure = failure
        self.calls = 0

    async def execute(self) -> NormalizationBatchResult:
        self.calls += 1
        self.shutdown.set()
        if self.failure is not None:
            raise self.failure
        return NormalizationBatchResult(claimed=2, completed=1, dead_lettered=1)


class IdleProcessor(StoppingProcessor):
    async def execute(self) -> NormalizationBatchResult:
        self.calls += 1
        self.shutdown.set()
        return NormalizationBatchResult()


class FakeDatabase:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


async def test_worker_commits_batch_then_stops_when_signalled() -> None:
    shutdown = asyncio.Event()
    processor = StoppingProcessor(shutdown)

    await worker_main(shutdown, settings=Settings(environment="test"), processor=processor)

    assert processor.calls == 1


async def test_worker_backs_off_after_failure_without_losing_process() -> None:
    shutdown = asyncio.Event()
    processor = StoppingProcessor(shutdown, failure=RuntimeError("internal detail"))

    await worker_main(shutdown, settings=Settings(environment="test"), processor=processor)

    assert processor.calls == 1


async def test_worker_stops_before_claiming_when_already_signalled() -> None:
    shutdown = asyncio.Event()
    shutdown.set()
    processor = StoppingProcessor(shutdown)

    await worker_main(shutdown, settings=Settings(environment="test"), processor=processor)

    assert processor.calls == 0


async def test_idle_worker_wait_path_observes_shutdown() -> None:
    shutdown = asyncio.Event()
    processor = IdleProcessor(shutdown)

    await worker_main(shutdown, settings=Settings(environment="test"), processor=processor)

    assert processor.calls == 1


async def test_worker_owns_and_closes_database_it_constructs() -> None:
    shutdown = asyncio.Event()
    shutdown.set()
    database = FakeDatabase()
    with patch("chakravyuh.worker.main.Database", return_value=database):
        await worker_main(shutdown, settings=Settings(environment="test"))

    assert database.closed is True


async def test_idle_wait_times_out_and_worker_identity_is_bounded() -> None:
    await _wait_for_shutdown(asyncio.Event(), 0.001)

    worker_id = _worker_id()
    assert ":" in worker_id
    assert len(worker_id) <= 255


async def test_signal_wrapper_delegates_to_worker() -> None:
    worker = AsyncMock()
    with patch("chakravyuh.worker.main.worker_main", worker):
        await _run_with_signals()

    worker.assert_awaited_once()


def test_worker_entrypoint() -> None:
    with patch("chakravyuh.worker.main.asyncio.run") as asyncio_run:
        run()

    asyncio_run.assert_called_once()
    asyncio_run.call_args.args[0].close()
