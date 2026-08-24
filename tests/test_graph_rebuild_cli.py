"""Graph rebuild CLI tests without live databases."""

import argparse
from typing import ClassVar
from unittest.mock import patch
from uuid import uuid4

import pytest

from chakravyuh.config import Settings
from chakravyuh.domain.errors import GraphRebuildNotAllowedError
from chakravyuh.operations import graph_rebuild


class FakeDatabase:
    instances: ClassVar[list["FakeDatabase"]] = []

    def __init__(self, settings: Settings) -> None:
        self.closed = False
        self.instances.append(self)

    async def close(self) -> None:
        self.closed = True


class SuccessfulRepository:
    def __init__(self, database: object) -> None:
        self.database = database

    async def request_rebuild(self, *, requested_by: str, reason: str):  # type: ignore[no-untyped-def]
        assert requested_by == "operator-1"
        assert reason == "Rebuild reviewed graph projection."
        return uuid4(), 12


class RejectedRepository(SuccessfulRepository):
    async def request_rebuild(self, *, requested_by: str, reason: str):  # type: ignore[no-untyped-def]
        raise GraphRebuildNotAllowedError("empty")


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        requested_by="operator-1",
        reason="Rebuild reviewed graph projection.",
    )


@pytest.mark.parametrize(
    ("repository", "expected"),
    [(SuccessfulRepository, 0), (RejectedRepository, 2)],
)
async def test_rebuild_cli_closes_database(repository: type, expected: int) -> None:
    FakeDatabase.instances.clear()
    with (
        patch("chakravyuh.operations.graph_rebuild.Database", FakeDatabase),
        patch(
            "chakravyuh.operations.graph_rebuild.PostgresGraphProjectionRepository",
            repository,
        ),
    ):
        exit_code = await graph_rebuild.rebuild_main(_args(), settings=Settings(environment="test"))
    assert exit_code == expected
    assert FakeDatabase.instances[-1].closed is True


def test_rebuild_parser_and_entrypoints() -> None:
    args = graph_rebuild._parser().parse_args(
        ["--requested-by", "operator-1", "--reason", "reviewed rebuild"]
    )
    assert args.requested_by == "operator-1"
    with pytest.raises(SystemExit):
        graph_rebuild._parser().parse_args([])

    with (
        patch("chakravyuh.operations.graph_rebuild._parser") as parser,
        patch("chakravyuh.operations.graph_rebuild.asyncio.run", return_value=0) as asyncio_run,
    ):
        parser.return_value.parse_args.return_value = _args()
        assert graph_rebuild.main([]) == 0
    asyncio_run.call_args.args[0].close()

    with (
        patch("chakravyuh.operations.graph_rebuild.main", return_value=2),
        pytest.raises(SystemExit, match="2"),
    ):
        graph_rebuild.run()
