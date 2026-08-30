"""CLI boundary tests for the explicitly budgeted live-AI experiment."""

from argparse import Namespace
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from chakravyuh.operations import recovery_arena_live_ai as cli


class _Dumpable:
    def __init__(self, **payload: object) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return self.payload


class _FakeDiagnostician:
    instances: ClassVar[list["_FakeDiagnostician"]] = []

    def __init__(self, settings: object, **options: object) -> None:
        self.settings = settings
        self.options = options
        self.closed = False
        self.instances.append(self)

    async def close(self) -> None:
        self.closed = True


def _patch_experiment(monkeypatch: pytest.MonkeyPatch, *, api_key: object | None) -> None:
    settings = SimpleNamespace(openrouter_model="test/model", openrouter_api_key=api_key)
    run_contract = SimpleNamespace(
        max_output_tokens=512,
        max_prompt_price_per_million_usd="0.10",
        max_completion_price_per_million_usd="0.20",
        model_dump=_Dumpable(run="contract").model_dump,
    )
    sample = SimpleNamespace(manifest=_Dumpable(sample="manifest"))
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "create_recovery_arena_contract", lambda: "contract")
    monkeypatch.setattr(cli, "generate_held_out_recovery_portfolio", lambda _: "portfolio")
    monkeypatch.setattr(cli, "build_live_ai_sample", lambda *_: sample)
    monkeypatch.setattr(cli, "create_live_ai_run_contract", lambda *_args, **_kwargs: run_contract)


@pytest.mark.asyncio
async def test_prepare_only_prints_the_locked_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_experiment(monkeypatch, api_key=None)

    result = await cli._run(
        Namespace(execute_live=False, acknowledge_max_cost_usd=None, checkpoint="unused")
    )

    assert result == 0
    assert '"live_execution": false' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_live_execution_requires_a_provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_experiment(monkeypatch, api_key=None)

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        await cli._run(
            Namespace(execute_live=True, acknowledge_max_cost_usd="1.00", checkpoint="unused")
        )


@pytest.mark.asyncio
async def test_live_execution_closes_provider_and_reports_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_experiment(monkeypatch, api_key=object())
    _FakeDiagnostician.instances.clear()
    monkeypatch.setattr(cli, "OpenRouterStructuredDiagnostician", _FakeDiagnostician)
    report = SimpleNamespace(passed=True, model_dump=_Dumpable(passed=True).model_dump)

    async def run_live(*_args: object, **options: Any) -> tuple[object, list[object]]:
        assert options["checkpoint_path"] == "checkpoint.jsonl"
        options["progress"](5, 10, 100)
        return report, []

    monkeypatch.setattr(cli, "run_live_ai_arena", run_live)

    result = await cli._run(
        Namespace(
            execute_live=True,
            acknowledge_max_cost_usd="1.00",
            checkpoint="checkpoint.jsonl",
        )
    )

    captured = capsys.readouterr()
    assert result == 0
    assert '"live_execution": true' in captured.out
    assert "live-AI progress: 5/10" in captured.err
    assert _FakeDiagnostician.instances[0].closed


def test_progress_only_reports_milestones(capsys: pytest.CaptureFixture[str]) -> None:
    cli._progress(3, 10, 20)
    assert capsys.readouterr().err == ""
