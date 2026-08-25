"""Recovery Arena contract and hidden held-out boundary tests."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from chakravyuh.domain.enums import ActionType, IncidentType
from chakravyuh.domain.recovery_arena import (
    ArenaDatasetRole,
    ArenaSeedPartition,
    RecoveryArenaContract,
    RecoveryArenaDatasetManifest,
    build_contract_hash,
    build_manifest_hash,
    create_held_out_manifest,
    create_recovery_arena_contract,
)
from chakravyuh.operations.recovery_arena_contract import main


def test_default_contract_locks_scope_scale_cost_and_partitions() -> None:
    contract = create_recovery_arena_contract()

    assert contract.recoverable_incident_types == (IncidentType.AUTHORIZED_NOT_CAPTURED,)
    assert contract.executable_actions == (ActionType.CAPTURE_PAYMENT,)
    assert contract.confirmation_event_types == ("payment.captured",)
    assert contract.live_model_call_limit == 100
    assert contract.live_model_cost_limit_microusd == 1_000_000
    assert contract.webhook_delivery_limit == 100_000
    assert contract.ingress_concurrency_limit == 50
    assert contract.partition(ArenaDatasetRole.HELD_OUT).seed_start == 50_000
    assert contract.partition(ArenaDatasetRole.HELD_OUT).seed_count == 667
    assert contract.contract_sha256 == build_contract_hash(contract)


def test_held_out_manifest_commits_10005_evaluator_only_cases() -> None:
    contract = create_recovery_arena_contract()
    manifest = create_held_out_manifest(contract)

    assert manifest.dataset_role is ArenaDatasetRole.HELD_OUT
    assert manifest.declared_case_count == 10_005
    assert manifest.oracle_visibility == "evaluator_only"
    assert manifest.contract_sha256 == contract.contract_sha256
    assert manifest.manifest_sha256 == build_manifest_hash(manifest)
    assert "expected" not in manifest.model_dump_json()
    assert "recoverable" not in manifest.model_dump_json()


def test_contract_and_manifest_hashes_are_reproducible() -> None:
    first = create_recovery_arena_contract()
    second = create_recovery_arena_contract()

    assert first == second
    assert create_held_out_manifest(first) == create_held_out_manifest(second)


def test_contract_cli_emits_machine_readable_commitments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main()

    output = json.loads(capsys.readouterr().out)
    assert output["contract"]["contract_sha256"] == (
        "b99775ca382196d5077b01caf0a675ee56f3b173f6be7ccf607edd458e87d1a3"
    )
    assert output["held_out_manifest"]["manifest_sha256"] == (
        "126b34cf79786ace693c8e0a60f24737574ed93cac804dcb27410e7507ad09a4"
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"scoring_currency": "USD"}, "INR"),
        ({"recoverable_incident_types": [IncidentType.FAILED_WITHOUT_RECOVERY]}, "authorized"),
        ({"executable_actions": [ActionType.CREATE_PAYMENT_LINK]}, "exact capture"),
        ({"confirmation_event_types": ["action.execution.succeeded"]}, "payment.captured"),
        ({"contract_sha256": "f" * 64}, "hash"),
    ],
)
def test_contract_rejects_scope_or_proof_rule_changes(change: dict[str, Any], message: str) -> None:
    contract = create_recovery_arena_contract()

    with pytest.raises(ValidationError, match=message):
        RecoveryArenaContract.model_validate({**contract.model_dump(), **change})


def test_contract_rejects_overlapping_seed_partitions() -> None:
    contract = create_recovery_arena_contract()
    partitions = list(contract.seed_partitions)
    partitions[-1] = ArenaSeedPartition(
        role=ArenaDatasetRole.HELD_OUT,
        seed_start=49_999,
        seed_count=667,
    )

    with pytest.raises(ValidationError, match="must not overlap"):
        RecoveryArenaContract.model_validate(
            {**contract.model_dump(), "seed_partitions": partitions}
        )


def test_contract_rejects_missing_partition_role() -> None:
    contract = create_recovery_arena_contract()

    with pytest.raises(ValidationError, match="one development"):
        RecoveryArenaContract.model_validate(
            {**contract.model_dump(), "seed_partitions": contract.seed_partitions[:-1]}
        )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"declared_case_count": 10_004}, "case count"),
        ({"oracle_visibility": "strategy_visible"}, "evaluator-only"),
        ({"dataset_role": ArenaDatasetRole.VALIDATION}, "held-out"),
        ({"revenue_confirmation_rule": "http_200"}, "authoritative webhook"),
        ({"manifest_sha256": "f" * 64}, "hash"),
    ],
)
def test_manifest_rejects_proof_boundary_tampering(change: dict[str, Any], message: str) -> None:
    manifest = create_held_out_manifest(create_recovery_arena_contract())

    with pytest.raises(ValidationError, match=message):
        RecoveryArenaDatasetManifest.model_validate({**manifest.model_dump(), **change})
