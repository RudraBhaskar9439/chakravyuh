"""Operator replay CLI tests without a live database."""

import argparse
from typing import ClassVar
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from chakravyuh.config import Settings
from chakravyuh.domain.errors import ReplayNotAllowedError
from chakravyuh.operations import replay


class FakeDatabase:
    instances: ClassVar[list["FakeDatabase"]] = []

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.closed = False
        self.instances.append(self)

    async def close(self) -> None:
        self.closed = True


class SuccessfulReplay:
    replay_id = uuid4()

    def __init__(self, repository: object) -> None:
        self.repository = repository

    async def execute(self, event_id: UUID, *, requested_by: str, reason: str) -> UUID:
        assert requested_by == "operator-1"
        assert reason == "A corrected normalizer is deployed."
        return self.replay_id


class RejectedReplay(SuccessfulReplay):
    async def execute(self, event_id: UUID, *, requested_by: str, reason: str) -> UUID:
        raise ReplayNotAllowedError("not dead-lettered")


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        event_id=uuid4(),
        requested_by="operator-1",
        reason="A corrected normalizer is deployed.",
    )


async def test_replay_cli_queues_and_closes_database() -> None:
    FakeDatabase.instances.clear()
    with (
        patch("chakravyuh.operations.replay.Database", FakeDatabase),
        patch("chakravyuh.operations.replay.PostgresNormalizationRepository"),
        patch("chakravyuh.operations.replay.RequestNormalizationReplay", SuccessfulReplay),
    ):
        exit_code = await replay.replay_main(_args(), settings=Settings(environment="test"))

    assert exit_code == 0
    assert FakeDatabase.instances[-1].closed is True


async def test_replay_cli_rejects_invalid_state_and_closes_database() -> None:
    FakeDatabase.instances.clear()
    with (
        patch("chakravyuh.operations.replay.Database", FakeDatabase),
        patch("chakravyuh.operations.replay.PostgresNormalizationRepository"),
        patch("chakravyuh.operations.replay.RequestNormalizationReplay", RejectedReplay),
    ):
        exit_code = await replay.replay_main(_args(), settings=Settings(environment="test"))

    assert exit_code == 2
    assert FakeDatabase.instances[-1].closed is True


def test_replay_parser_requires_a_uuid_and_audit_context() -> None:
    event_id = uuid4()
    args = replay._parser().parse_args(
        [str(event_id), "--requested-by", "operator-1", "--reason", "safe replay"]
    )

    assert args.event_id == event_id
    with pytest.raises(SystemExit):
        replay._parser().parse_args(["not-a-uuid"])


def test_replay_main_entrypoint_runs_async_command() -> None:
    with (
        patch("chakravyuh.operations.replay._parser") as parser,
        patch("chakravyuh.operations.replay.asyncio.run", return_value=0) as asyncio_run,
    ):
        parser.return_value.parse_args.return_value = _args()
        assert replay.main([]) == 0

    asyncio_run.assert_called_once()
    asyncio_run.call_args.args[0].close()


def test_replay_console_script_exits_with_command_status() -> None:
    with (
        patch("chakravyuh.operations.replay.main", return_value=2),
        pytest.raises(
            SystemExit,
            match="2",
        ),
    ):
        replay.run()
