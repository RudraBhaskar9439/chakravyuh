"""Grounded diagnosis worker lifecycle tests."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from chakravyuh.application.diagnosis import DiagnosisBatchResult
from chakravyuh.config import Settings
from chakravyuh.diagnosis_worker.main import (
    _run_with_signals,
    _worker_id,
    diagnosis_worker_main,
    run,
)


class _StoppingProcessor:
    def __init__(
        self,
        shutdown: asyncio.Event,
        *,
        idle: bool = False,
        failure: Exception | None = None,
    ) -> None:
        self.shutdown = shutdown
        self.idle = idle
        self.failure = failure
        self.calls = 0

    async def execute(self) -> DiagnosisBatchResult:
        self.calls += 1
        self.shutdown.set()
        if self.failure is not None:
            raise self.failure
        if self.idle:
            return DiagnosisBatchResult()
        return DiagnosisBatchResult(claimed=2, completed=1, retried=1)


class _Closable:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


async def test_diagnosis_worker_commits_and_isolates_idle_or_batch_failure() -> None:
    for processor in (
        _StoppingProcessor(asyncio.Event()),
        _StoppingProcessor(asyncio.Event(), idle=True),
        _StoppingProcessor(asyncio.Event(), failure=RuntimeError("test failure")),
    ):
        await diagnosis_worker_main(
            processor.shutdown,
            settings=Settings(environment="test"),
            processor=processor,
        )
        assert processor.calls == 1


async def test_diagnosis_worker_stops_before_claim_when_signalled() -> None:
    shutdown = asyncio.Event()
    shutdown.set()
    processor = _StoppingProcessor(shutdown)

    await diagnosis_worker_main(
        shutdown,
        settings=Settings(environment="test"),
        processor=processor,
    )

    assert processor.calls == 0


async def test_diagnosis_worker_owns_and_closes_all_dependencies() -> None:
    shutdown = asyncio.Event()
    shutdown.set()
    database = _Closable()
    reader = _Closable()
    diagnostician = _Closable()
    with (
        patch("chakravyuh.diagnosis_worker.main.Database", return_value=database),
        patch("chakravyuh.diagnosis_worker.main.Neo4jEvidenceReader", return_value=reader),
        patch(
            "chakravyuh.diagnosis_worker.main.GeminiStructuredDiagnostician",
            return_value=diagnostician,
        ),
    ):
        await diagnosis_worker_main(shutdown, settings=Settings(environment="test"))

    assert database.closed is True
    assert reader.closed is True
    assert diagnostician.closed is True


async def test_diagnosis_worker_closes_partial_dependencies_when_startup_fails() -> None:
    database = _Closable()
    diagnostician = _Closable()
    with (
        patch("chakravyuh.diagnosis_worker.main.Database", return_value=database),
        patch(
            "chakravyuh.diagnosis_worker.main.Neo4jEvidenceReader",
            side_effect=RuntimeError("neo4j setup failed"),
        ),
        patch(
            "chakravyuh.diagnosis_worker.main.GeminiStructuredDiagnostician",
            return_value=diagnostician,
        ),
        pytest.raises(RuntimeError, match="neo4j setup failed"),
    ):
        await diagnosis_worker_main(
            asyncio.Event(),
            settings=Settings(environment="test"),
        )

    assert database.closed is True
    assert diagnostician.closed is True


async def test_diagnosis_signal_wrapper_delegates() -> None:
    worker = AsyncMock()
    with patch("chakravyuh.diagnosis_worker.main.diagnosis_worker_main", worker):
        await _run_with_signals()
    worker.assert_awaited_once()


def test_diagnosis_worker_identity_and_entrypoint() -> None:
    assert _worker_id().startswith("diagnosis:")
    assert len(_worker_id()) <= 255
    with patch("chakravyuh.diagnosis_worker.main.asyncio.run") as asyncio_run:
        run()
    asyncio_run.assert_called_once()
    asyncio_run.call_args.args[0].close()
