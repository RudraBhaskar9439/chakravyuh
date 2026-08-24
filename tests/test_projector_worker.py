"""Graph projection worker lifecycle tests."""

import asyncio
from unittest.mock import AsyncMock, patch

from chakravyuh.application.graph_projection import GraphProjectionBatchResult
from chakravyuh.application.graph_rebuild import GraphRebuildFinalizationResult
from chakravyuh.config import Settings
from chakravyuh.projector_worker.main import (
    _run_with_signals,
    _worker_id,
    projector_worker_main,
    run,
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

    async def execute(self) -> GraphProjectionBatchResult:
        self.calls += 1
        self.shutdown.set()
        if self.failure is not None:
            raise self.failure
        return GraphProjectionBatchResult(claimed=2, completed=1, retried=1)


class IdleProcessor(StoppingProcessor):
    async def execute(self) -> GraphProjectionBatchResult:
        self.calls += 1
        self.shutdown.set()
        return GraphProjectionBatchResult()


class RebuildFinalizer:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls = 0

    async def execute(self) -> GraphRebuildFinalizationResult:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return GraphRebuildFinalizationResult(candidates=1, completed=1)


class FakeDatabase:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeProjector:
    def __init__(self) -> None:
        self.initialized = False
        self.closed = False

    async def initialize_schema(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True


async def test_projector_worker_commits_and_handles_idle_or_failure() -> None:
    for processor in (
        StoppingProcessor(asyncio.Event()),
        IdleProcessor(asyncio.Event()),
        StoppingProcessor(asyncio.Event(), failure=RuntimeError("test failure")),
    ):
        await projector_worker_main(
            processor.shutdown,
            settings=Settings(environment="test"),
            processor=processor,
        )
        assert processor.calls == 1


async def test_projector_worker_stops_before_claim_when_signalled() -> None:
    shutdown = asyncio.Event()
    shutdown.set()
    processor = StoppingProcessor(shutdown)

    await projector_worker_main(
        shutdown,
        settings=Settings(environment="test"),
        processor=processor,
    )

    assert processor.calls == 0


async def test_projector_worker_finalizes_rebuild_or_isolates_its_failure() -> None:
    for finalizer in (
        RebuildFinalizer(),
        RebuildFinalizer(failure=RuntimeError("test finalization failure")),
    ):
        shutdown = asyncio.Event()
        await projector_worker_main(
            shutdown,
            settings=Settings(environment="test"),
            processor=StoppingProcessor(shutdown),
            finalizer=finalizer,
        )
        assert finalizer.calls == 1


async def test_projector_worker_owns_initialized_dependencies() -> None:
    shutdown = asyncio.Event()
    shutdown.set()
    database = FakeDatabase()
    projector = FakeProjector()
    with (
        patch("chakravyuh.projector_worker.main.Database", return_value=database),
        patch(
            "chakravyuh.projector_worker.main.Neo4jPaymentGraphProjector",
            return_value=projector,
        ),
    ):
        await projector_worker_main(shutdown, settings=Settings(environment="test"))

    assert projector.initialized is True
    assert projector.closed is True
    assert database.closed is True


async def test_projector_signal_wrapper_delegates() -> None:
    worker = AsyncMock()
    with patch("chakravyuh.projector_worker.main.projector_worker_main", worker):
        await _run_with_signals()
    worker.assert_awaited_once()


def test_projector_worker_identity_and_entrypoint() -> None:
    assert _worker_id().startswith("graph:")
    assert len(_worker_id()) <= 255
    with patch("chakravyuh.projector_worker.main.asyncio.run") as asyncio_run:
        run()
    asyncio_run.assert_called_once()
    asyncio_run.call_args.args[0].close()
