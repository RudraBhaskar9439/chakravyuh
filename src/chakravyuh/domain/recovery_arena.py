"""Versioned, tamper-evident contract for the Recovery Arena benchmark."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from itertools import pairwise
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chakravyuh.domain.enums import ActionType, IncidentType


class ArenaDatasetRole(StrEnum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    HELD_OUT = "held_out"


class ArenaStrategyName(StrEnum):
    NO_INTERVENTION = "no_intervention"
    RETRY_ALL = "retry_all"
    CHAKRAVYUH = "chakravyuh"


class ArenaSeedPartition(BaseModel):
    """A disjoint deterministic identity range, not a collection of training records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: ArenaDatasetRole
    seed_start: int = Field(ge=0)
    seed_count: int = Field(ge=1, le=100_000)

    @property
    def seed_end_exclusive(self) -> int:
        return self.seed_start + self.seed_count


class RecoveryArenaContract(BaseModel):
    """The rules and resource bounds fixed before the held-out arena is executed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str = Field(pattern=r"^recovery-arena-contract-v[0-9]+$")
    dataset_generator_version: str = Field(pattern=r"^recovery-arena-generator-v[0-9]+$")
    strategies: tuple[ArenaStrategyName, ...]
    seed_partitions: tuple[ArenaSeedPartition, ...]
    cases_per_seed: int = Field(ge=1, le=100)
    scoring_currency: str = Field(pattern=r"^[A-Z]{3}$")
    recoverable_incident_types: tuple[IncidentType, ...]
    executable_actions: tuple[ActionType, ...]
    confirmation_event_types: tuple[str, ...]
    manual_review_cost_subunits: int = Field(ge=0)
    incorrect_action_cost_subunits: int = Field(ge=0)
    live_model_call_limit: int = Field(ge=0, le=1_000)
    live_model_cost_limit_microusd: int = Field(ge=0, le=100_000_000)
    webhook_delivery_limit: int = Field(ge=1, le=1_000_000)
    ingress_concurrency_limit: int = Field(ge=1, le=500)
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_locked_contract(self) -> Self:
        expected_roles = set(ArenaDatasetRole)
        roles = [partition.role for partition in self.seed_partitions]
        if len(roles) != len(expected_roles) or set(roles) != expected_roles:
            msg = "recovery arena requires one development, validation, and held-out partition"
            raise ValueError(msg)
        ordered = sorted(self.seed_partitions, key=lambda item: item.seed_start)
        for previous, current in pairwise(ordered):
            if previous.seed_end_exclusive > current.seed_start:
                msg = "recovery arena seed partitions must not overlap"
                raise ValueError(msg)
        if self.strategies != tuple(ArenaStrategyName):
            msg = "recovery arena v1 requires all three strategies in canonical order"
            raise ValueError(msg)
        if self.scoring_currency != "INR":
            msg = "recovery arena v1 scores exact INR subunits only"
            raise ValueError(msg)
        if self.recoverable_incident_types != (IncidentType.AUTHORIZED_NOT_CAPTURED,):
            msg = "recovery arena v1 recovers only authorized-not-captured incidents"
            raise ValueError(msg)
        if self.executable_actions != (ActionType.CAPTURE_PAYMENT,):
            msg = "recovery arena v1 executes only exact capture"
            raise ValueError(msg)
        if self.confirmation_event_types != ("payment.captured",):
            msg = "recovery arena v1 credits revenue only after payment.captured"
            raise ValueError(msg)
        if build_contract_hash(self) != self.contract_sha256:
            msg = "recovery arena contract hash does not match its canonical content"
            raise ValueError(msg)
        return self

    def partition(self, role: ArenaDatasetRole) -> ArenaSeedPartition:
        return next(item for item in self.seed_partitions if item.role is role)


class RecoveryArenaDatasetManifest(BaseModel):
    """Stable commitment to the evaluation identity range and generator contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: str = Field(pattern=r"^recovery-arena-manifest-v[0-9]+$")
    dataset_role: ArenaDatasetRole
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generator_version: str = Field(pattern=r"^recovery-arena-generator-v[0-9]+$")
    seed_start: int = Field(ge=0)
    seed_count: int = Field(ge=1)
    cases_per_seed: int = Field(ge=1)
    declared_case_count: int = Field(ge=1)
    oracle_visibility: str
    revenue_confirmation_rule: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.dataset_role is not ArenaDatasetRole.HELD_OUT:
            msg = "judge manifest must commit only the held-out partition"
            raise ValueError(msg)
        if self.declared_case_count != self.seed_count * self.cases_per_seed:
            msg = "declared case count must equal seed count times cases per seed"
            raise ValueError(msg)
        if self.oracle_visibility != "evaluator_only":
            msg = "held-out oracle labels must remain evaluator-only"
            raise ValueError(msg)
        if self.revenue_confirmation_rule != "authoritative_payment_captured_webhook":
            msg = "manifest must require authoritative webhook confirmation"
            raise ValueError(msg)
        if build_manifest_hash(self) != self.manifest_sha256:
            msg = "recovery arena manifest hash does not match its canonical content"
            raise ValueError(msg)
        return self


def create_recovery_arena_contract() -> RecoveryArenaContract:
    """Create the immutable v1 benchmark contract with conservative local-machine bounds."""

    draft = RecoveryArenaContract.model_construct(
        contract_version="recovery-arena-contract-v1",
        dataset_generator_version="recovery-arena-generator-v1",
        strategies=tuple(ArenaStrategyName),
        seed_partitions=(
            ArenaSeedPartition(
                role=ArenaDatasetRole.DEVELOPMENT,
                seed_start=0,
                seed_count=40_000,
            ),
            ArenaSeedPartition(
                role=ArenaDatasetRole.VALIDATION,
                seed_start=40_000,
                seed_count=10_000,
            ),
            ArenaSeedPartition(
                role=ArenaDatasetRole.HELD_OUT,
                seed_start=50_000,
                seed_count=667,
            ),
        ),
        cases_per_seed=15,
        scoring_currency="INR",
        recoverable_incident_types=(IncidentType.AUTHORIZED_NOT_CAPTURED,),
        executable_actions=(ActionType.CAPTURE_PAYMENT,),
        confirmation_event_types=("payment.captured",),
        manual_review_cost_subunits=2_000,
        incorrect_action_cost_subunits=10_000,
        live_model_call_limit=100,
        live_model_cost_limit_microusd=1_000_000,
        webhook_delivery_limit=100_000,
        ingress_concurrency_limit=50,
        contract_sha256="0" * 64,
    )
    return RecoveryArenaContract.model_validate(
        {**draft.model_dump(mode="json"), "contract_sha256": build_contract_hash(draft)}
    )


def create_held_out_manifest(
    contract: RecoveryArenaContract,
) -> RecoveryArenaDatasetManifest:
    """Commit to the held-out seed range without generating or revealing its oracle labels."""

    partition = contract.partition(ArenaDatasetRole.HELD_OUT)
    draft = RecoveryArenaDatasetManifest.model_construct(
        manifest_version="recovery-arena-manifest-v1",
        dataset_role=ArenaDatasetRole.HELD_OUT,
        contract_sha256=contract.contract_sha256,
        generator_version=contract.dataset_generator_version,
        seed_start=partition.seed_start,
        seed_count=partition.seed_count,
        cases_per_seed=contract.cases_per_seed,
        declared_case_count=partition.seed_count * contract.cases_per_seed,
        oracle_visibility="evaluator_only",
        revenue_confirmation_rule="authoritative_payment_captured_webhook",
        manifest_sha256="0" * 64,
    )
    return RecoveryArenaDatasetManifest.model_validate(
        {**draft.model_dump(mode="json"), "manifest_sha256": build_manifest_hash(draft)}
    )


def build_contract_hash(contract: RecoveryArenaContract) -> str:
    return _canonical_hash(contract.model_dump(mode="json", exclude={"contract_sha256"}))


def build_manifest_hash(manifest: RecoveryArenaDatasetManifest) -> str:
    return _canonical_hash(manifest.model_dump(mode="json", exclude={"manifest_sha256"}))


def _canonical_hash(value: object) -> str:
    body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()
