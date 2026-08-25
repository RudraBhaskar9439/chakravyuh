"""Revision-bound Recovery Arena proof-pack tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from chakravyuh.domain.recovery_arena import ArenaDatasetRole, create_recovery_arena_contract
from chakravyuh.operations.recovery_proof_pack import (
    ProofPackVerificationError,
    RecoveryProofPackManifest,
    build_recovery_proof_pack,
    main,
    verify_recovery_proof_pack,
)
from chakravyuh.simulation.recovery_portfolio import generate_recovery_portfolio

_REVISION = "a" * 40


async def _build_small(path: Path) -> RecoveryProofPackManifest:
    contract = create_recovery_arena_contract()
    portfolio = generate_recovery_portfolio(
        contract,
        dataset_role=ArenaDatasetRole.VALIDATION,
        seed_start=40_000,
        seed_count=10,
    )
    return await build_recovery_proof_pack(
        path,
        code_revision=_REVISION,
        contract=contract,
        portfolio=portfolio,
    )


async def test_proof_pack_is_complete_revision_bound_and_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    manifest = await _build_small(first)
    replay = await _build_small(second)

    assert manifest == replay
    assert manifest.case_count == 150
    assert manifest.code_revision == _REVISION
    assert manifest.tournament_passed
    assert {item.name for item in first.iterdir()} == {
        "SHA256SUMS",
        "cases.jsonl",
        "index.html",
        "manifest.json",
        "strategy-summary.csv",
    }
    for artifact in first.iterdir():
        assert artifact.read_bytes() == (second / artifact.name).read_bytes()
    assert (
        verify_recovery_proof_pack(
            first,
            expected_code_revision=_REVISION,
            expected_proof_root=manifest.proof_root_sha256,
        )
        == manifest
    )


async def test_proof_pack_negative_control_rejects_one_modified_byte(tmp_path: Path) -> None:
    output = tmp_path / "proof"
    await _build_small(output)
    cases = output / "cases.jsonl"
    cases.write_bytes(cases.read_bytes().replace(b'"case_index":0', b'"case_index":9', 1))

    with pytest.raises(ProofPackVerificationError, match="SHA256SUMS"):
        verify_recovery_proof_pack(output, expected_code_revision=_REVISION)


async def test_proof_pack_refuses_overwrite_and_wrong_trust_anchor(tmp_path: Path) -> None:
    output = tmp_path / "proof"
    manifest = await _build_small(output)

    with pytest.raises(FileExistsError, match="already exists"):
        await _build_small(output)
    with pytest.raises(ProofPackVerificationError, match="different code revision"):
        verify_recovery_proof_pack(output, expected_code_revision="b" * 40)
    with pytest.raises(ProofPackVerificationError, match="trusted root"):
        verify_recovery_proof_pack(output, expected_proof_root="b" * 64)
    assert manifest.proof_root_sha256


async def test_proof_pack_cli_verifies_and_rejects_invalid_build_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "proof"
    await _build_small(output)

    assert main(["verify", "--input-dir", str(output)]) == 0
    assert "proof_root_sha256" in capsys.readouterr().out
    assert (
        main(
            [
                "build",
                "--output-dir",
                str(tmp_path / "invalid"),
                "--code-revision",
                "short",
            ]
        )
        == 2
    )
    assert "40-character Git SHA" in capsys.readouterr().err
