"""Tests for the constrained single-container hosted runtime."""

import asyncio
from collections.abc import Awaitable
from typing import Any

import pytest

from chakravyuh import hosted
from chakravyuh.config import Settings


def test_hosted_port_prefers_provider_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "18080")

    assert hosted._hosted_port(Settings()) == 18_080


@pytest.mark.parametrize("value", ["invalid", "0", "65536"])
def test_hosted_port_rejects_invalid_provider_port(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("PORT", value)

    with pytest.raises(ValueError, match="PORT must"):
        hosted._hosted_port(Settings())


async def test_hosted_runtime_stops_all_processors_with_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []

    class FakeServer:
        def __init__(self, _: object) -> None:
            pass

        async def serve(self) -> None:
            lifecycle.append("api-started")
            await asyncio.sleep(0)
            lifecycle.append("api-stopped")

    async def processor(
        event: asyncio.Event,
        **_: Any,
    ) -> None:
        lifecycle.append("processor-started")
        await event.wait()
        lifecycle.append("processor-stopped")

    monkeypatch.setattr(hosted, "Server", FakeServer)
    monkeypatch.setattr(hosted, "worker_main", processor)
    monkeypatch.setattr(hosted, "projector_worker_main", processor)
    monkeypatch.setattr(hosted, "diagnosis_worker_main", processor)

    await hosted.hosted_main(Settings())

    assert lifecycle.count("processor-started") == 3
    assert lifecycle.count("processor-stopped") == 3
    assert lifecycle.index("api-stopped") < lifecycle.index("processor-stopped")


def test_run_starts_hosted_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Awaitable[None]] = []
    migrations: list[tuple[object, str]] = []

    def fake_run(awaitable: Awaitable[None]) -> None:
        captured.append(awaitable)
        awaitable.close()  # type: ignore[attr-defined]

    def fake_upgrade(configuration: object, revision: str) -> None:
        migrations.append((configuration, revision))

    monkeypatch.setattr(asyncio, "run", fake_run)
    monkeypatch.setattr(hosted, "upgrade", fake_upgrade)

    hosted.run()

    assert len(captured) == 1
    assert len(migrations) == 1
    assert migrations[0][1] == "head"
