"""Journey rebuild CLI tests without a live database."""

import argparse
from typing import ClassVar
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from chakravyuh.config import Settings
from chakravyuh.domain.errors import JourneyReductionReplayNotAllowedError
from chakravyuh.operations import journey_replay


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

    async def execute(
        self,
        merchant_id: str,
        correlation_id: str,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID:
        assert merchant_id == "merchant-1"
        assert correlation_id == "order-1"
        assert requested_by == "operator-1"
        assert reason == "A reviewed reducer is deployed."
        return self.replay_id


class RejectedReplay(SuccessfulReplay):
    async def execute(
        self,
        merchant_id: str,
        correlation_id: str,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID:
        raise JourneyReductionReplayNotAllowedError("pending")


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        merchant_id="merchant-1",
        correlation_id="order-1",
        requested_by="operator-1",
        reason="A reviewed reducer is deployed.",
    )


@pytest.mark.parametrize(
    ("use_case", "expected"),
    [(SuccessfulReplay, 0), (RejectedReplay, 2)],
)
async def test_journey_replay_closes_database(use_case: type, expected: int) -> None:
    FakeDatabase.instances.clear()
    with (
        patch("chakravyuh.operations.journey_replay.Database", FakeDatabase),
        patch("chakravyuh.operations.journey_replay.PostgresJourneyReductionRepository"),
        patch("chakravyuh.operations.journey_replay.RequestJourneyReductionReplay", use_case),
    ):
        exit_code = await journey_replay.replay_main(_args(), settings=Settings(environment="test"))

    assert exit_code == expected
    assert FakeDatabase.instances[-1].closed is True


def test_journey_replay_parser_requires_audit_context() -> None:
    args = journey_replay._parser().parse_args(
        [
            "merchant-1",
            "order-1",
            "--requested-by",
            "operator-1",
            "--reason",
            "safe rebuild",
        ]
    )
    assert args.correlation_id == "order-1"
    with pytest.raises(SystemExit):
        journey_replay._parser().parse_args(["merchant-1", "order-1"])


def test_journey_replay_entrypoints() -> None:
    with (
        patch("chakravyuh.operations.journey_replay._parser") as parser,
        patch("chakravyuh.operations.journey_replay.asyncio.run", return_value=0) as asyncio_run,
    ):
        parser.return_value.parse_args.return_value = _args()
        assert journey_replay.main([]) == 0
    asyncio_run.call_args.args[0].close()

    with (
        patch("chakravyuh.operations.journey_replay.main", return_value=2),
        pytest.raises(SystemExit, match="2"),
    ):
        journey_replay.run()
