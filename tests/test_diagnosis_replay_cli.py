"""Diagnosis replay CLI tests without a live database."""

import argparse
from typing import ClassVar
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from chakravyuh.config import Settings
from chakravyuh.domain.errors import DiagnosisReplayNotAllowedError
from chakravyuh.operations import diagnosis_replay


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

    async def execute(self, incident_id: UUID, *, requested_by: str, reason: str) -> UUID:
        assert requested_by == "operator-1"
        assert reason == "The temporary model quota recovered."
        return self.replay_id


class RejectedReplay(SuccessfulReplay):
    async def execute(self, incident_id: UUID, *, requested_by: str, reason: str) -> UUID:
        raise DiagnosisReplayNotAllowedError("not dead-lettered")


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        incident_id=uuid4(),
        requested_by="operator-1",
        reason="The temporary model quota recovered.",
    )


@pytest.mark.parametrize(
    ("use_case", "expected"),
    [(SuccessfulReplay, 0), (RejectedReplay, 2)],
)
async def test_diagnosis_replay_closes_database(use_case: type, expected: int) -> None:
    FakeDatabase.instances.clear()
    with (
        patch("chakravyuh.operations.diagnosis_replay.Database", FakeDatabase),
        patch("chakravyuh.operations.diagnosis_replay.PostgresDiagnosisRepository"),
        patch("chakravyuh.operations.diagnosis_replay.RequestDiagnosisReplay", use_case),
    ):
        exit_code = await diagnosis_replay.replay_main(
            _args(),
            settings=Settings(environment="test"),
        )

    assert exit_code == expected
    assert FakeDatabase.instances[-1].closed is True


def test_diagnosis_replay_parser_requires_audit_context() -> None:
    incident_id = uuid4()
    args = diagnosis_replay._parser().parse_args(
        [str(incident_id), "--requested-by", "operator-1", "--reason", "safe replay"]
    )
    assert args.incident_id == incident_id
    with pytest.raises(SystemExit):
        diagnosis_replay._parser().parse_args([str(incident_id)])


def test_diagnosis_replay_entrypoints() -> None:
    with (
        patch("chakravyuh.operations.diagnosis_replay._parser") as parser,
        patch("chakravyuh.operations.diagnosis_replay.asyncio.run", return_value=0) as asyncio_run,
    ):
        parser.return_value.parse_args.return_value = _args()
        assert diagnosis_replay.main([]) == 0
    asyncio_run.call_args.args[0].close()

    with (
        patch("chakravyuh.operations.diagnosis_replay.main", return_value=2),
        pytest.raises(SystemExit, match="2"),
    ):
        diagnosis_replay.run()
