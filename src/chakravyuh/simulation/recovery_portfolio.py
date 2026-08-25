"""Deterministic economic portfolio with a strict observed/oracle boundary."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.enums import ActionType, EntityType, EventSource, IncidentType, PaymentStatus
from chakravyuh.domain.events import EntityReference, NormalizedEvent
from chakravyuh.domain.journeys import JourneyEntityState, reduce_payment_journey
from chakravyuh.domain.money import Money
from chakravyuh.domain.recovery_arena import (
    ArenaDatasetRole,
    RecoveryArenaContract,
    create_recovery_arena_contract,
)
from chakravyuh.simulation.faults import FaultCase, generate_fault_set
from chakravyuh.simulation.razorpay_twin import (
    ArenaProviderFault,
    ArenaProviderPlan,
    create_provider_plan,
)

PORTFOLIO_VERSION = "recovery-arena-portfolio-v1"
_BASE_AMOUNT_SUBUNITS = 10_000
_AMOUNT_LADDER_SUBUNITS = (1_000, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000)
_MERCHANT_COUNT = 25


class ArenaCaseFamily(StrEnum):
    CAPTURED_ORDER_UNPAID = "captured-order-unpaid"
    AUTHORIZED_NOT_CAPTURED = "authorized-not-captured"
    FAILED_WITHOUT_RECOVERY = "failed-without-recovery"
    STALE_RECOVERY_LINK = "stale-recovery-link"
    DUPLICATE_RECOVERY_LINKS = "duplicate-recovery-links"
    TERMINAL_REGRESSION = "terminal-regression"
    SUCCESSFUL_PAYMENT = "successful_payment"
    FAILED_THEN_RECOVERED = "failed_then_recovered"
    PARTIALLY_REFUNDED = "partially_refunded"
    OUT_OF_ORDER_DELIVERY = "out_of_order_delivery"
    DUPLICATE_DELIVERY = "duplicate_delivery"
    CAPTURED_UNPAID_WITHIN_GRACE = "captured-unpaid-within-grace"
    AUTHORIZED_WITHIN_GRACE = "authorized-within-grace"
    SINGLE_ACTIVE_LINK_BEFORE_PAYMENT = "single-active-link-before-payment"
    INACTIVE_LINK_AFTER_SUCCESS = "inactive-link-after-success"


class ArenaMerchantPolicy(BaseModel):
    """Observed merchant-owned boundary supplied to every strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: str = "arena-merchant-policy-v1"
    merchant_id: str
    capture_enabled: bool
    maximum_capture_subunits: int = Field(gt=0)
    independent_checker_required: bool = True
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_policy_hash(self) -> ArenaMerchantPolicy:
        if _model_hash(self, exclude={"policy_sha256"}) != self.policy_sha256:
            msg = "arena merchant policy hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ArenaObservedCase(BaseModel):
    """Complete strategy input: opaque identity, observed history, and merchant policy only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^case_[0-9a-f]{32}$")
    merchant_id: str
    correlation_id: str
    evaluated_at: AwareDatetime
    events: tuple[NormalizedEvent, ...]
    merchant_policy: ArenaMerchantPolicy
    observed_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_observed_case(self) -> ArenaObservedCase:
        if not self.events:
            msg = "arena observed case requires at least one event"
            raise ValueError(msg)
        if any(
            event.merchant_id != self.merchant_id or event.correlation_id != self.correlation_id
            for event in self.events
        ):
            msg = "arena observed events must share merchant and correlation identity"
            raise ValueError(msg)
        if self.merchant_policy.merchant_id != self.merchant_id:
            msg = "arena merchant policy must match the observed merchant"
            raise ValueError(msg)
        if _model_hash(self, exclude={"observed_case_sha256"}) != self.observed_case_sha256:
            msg = "arena observed-case hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ArenaOracleCase(BaseModel):
    """Evaluator-only labels and predetermined provider behavior never passed to a strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^case_[0-9a-f]{32}$")
    seed: int = Field(ge=0)
    family: ArenaCaseFamily
    expected_incident_type: IncidentType | None = None
    expected_affected_entity: EntityReference | None = None
    payment_amount: Money
    action_eligible: bool
    recoverable: bool
    expected_action: ActionType | None = None
    provider_plan: ArenaProviderPlan
    oracle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_oracle(self) -> ArenaOracleCase:
        if (self.expected_incident_type is None) != (self.expected_affected_entity is None):
            msg = "arena incident type and affected entity must be present together"
            raise ValueError(msg)
        if self.action_eligible != (self.expected_action is ActionType.CAPTURE_PAYMENT):
            msg = "arena action eligibility must agree with exact capture expectation"
            raise ValueError(msg)
        if self.recoverable and not self.action_eligible:
            msg = "arena recoverable case must first be action-eligible"
            raise ValueError(msg)
        if self.provider_plan.case_id != self.case_id:
            msg = "arena provider plan must match its oracle case"
            raise ValueError(msg)
        if self.provider_plan.initial_state.amount != self.payment_amount:
            msg = "arena provider amount must match the oracle payment amount"
            raise ValueError(msg)
        if _model_hash(self, exclude={"oracle_sha256"}) != self.oracle_sha256:
            msg = "arena oracle hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ArenaEvaluationCase(BaseModel):
    """Evaluator envelope; callers must pass only `observed` into a strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observed: ArenaObservedCase
    oracle: ArenaOracleCase

    @model_validator(mode="after")
    def validate_boundary(self) -> ArenaEvaluationCase:
        if self.observed.case_id != self.oracle.case_id:
            msg = "arena observed and oracle case identities must match"
            raise ValueError(msg)
        if self.observed.merchant_id != self.oracle.provider_plan.merchant_id:
            msg = "arena provider plan merchant must match observed merchant"
            raise ValueError(msg)
        return self


class ArenaPortfolioManifest(BaseModel):
    """Aggregate and Merkle-style commitment for one deterministic portfolio."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    portfolio_version: str = PORTFOLIO_VERSION
    dataset_role: ArenaDatasetRole
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_start: int = Field(ge=0)
    seed_count: int = Field(ge=1)
    case_count: int = Field(ge=1)
    merchant_count: int = Field(ge=1)
    scoring_currency: str = "INR"
    synthetic_payment_volume_subunits: int = Field(ge=0)
    oracle_recoverable_revenue_subunits: int = Field(ge=0)
    family_counts: dict[str, int]
    provider_fault_counts: dict[str, int]
    observed_cases_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    oracle_cases_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> ArenaPortfolioManifest:
        if self.case_count != sum(self.family_counts.values()):
            msg = "arena family distribution must account for every case"
            raise ValueError(msg)
        if self.case_count != sum(self.provider_fault_counts.values()):
            msg = "arena provider-fault distribution must account for every case"
            raise ValueError(msg)
        if _model_hash(self, exclude={"manifest_sha256"}) != self.manifest_sha256:
            msg = "arena portfolio manifest hash does not match its canonical content"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class RecoveryPortfolio:
    manifest: ArenaPortfolioManifest
    cases: tuple[ArenaEvaluationCase, ...]


def generate_held_out_recovery_portfolio(
    contract: RecoveryArenaContract | None = None,
) -> RecoveryPortfolio:
    locked = contract or create_recovery_arena_contract()
    partition = locked.partition(ArenaDatasetRole.HELD_OUT)
    return generate_recovery_portfolio(
        locked,
        dataset_role=ArenaDatasetRole.HELD_OUT,
        seed_start=partition.seed_start,
        seed_count=partition.seed_count,
    )


def generate_recovery_portfolio(
    contract: RecoveryArenaContract,
    *,
    dataset_role: ArenaDatasetRole,
    seed_start: int,
    seed_count: int,
) -> RecoveryPortfolio:
    partition = contract.partition(dataset_role)
    if seed_count < 1:
        msg = "arena portfolio requires at least one seed"
        raise ValueError(msg)
    if seed_start < partition.seed_start or seed_start + seed_count > partition.seed_end_exclusive:
        msg = "arena portfolio seed range must remain inside its declared partition"
        raise ValueError(msg)
    fault_cases = generate_fault_set(range(seed_start, seed_start + seed_count))
    if len(fault_cases) != seed_count * contract.cases_per_seed:
        msg = "arena generator case count no longer matches the locked contract"
        raise ValueError(msg)
    cases = tuple(_economic_case(item) for item in fault_cases)
    manifest = _portfolio_manifest(
        contract,
        dataset_role=dataset_role,
        seed_start=seed_start,
        seed_count=seed_count,
        cases=cases,
    )
    return RecoveryPortfolio(manifest=manifest, cases=cases)


def _economic_case(fault_case: FaultCase) -> ArenaEvaluationCase:
    family_name, _, _ = fault_case.case_id.partition(":")
    family = ArenaCaseFamily(family_name)
    case_id = f"case_{uuid5(NAMESPACE_URL, f'chakravyuh:arena-case:{fault_case.case_id}').hex}"
    merchant_index = fault_case.seed % _MERCHANT_COUNT
    merchant_id = f"merchant_arena{merchant_index:02d}"
    amount_subunits = _amount_for_case(case_id)
    events, identity_map = _rewrite_events(
        fault_case.events,
        case_id=case_id,
        merchant_id=merchant_id,
        amount_subunits=amount_subunits,
    )
    policy = _merchant_policy(merchant_id, merchant_index)
    observed = _observed_case(
        case_id=case_id,
        merchant_id=merchant_id,
        evaluated_at=fault_case.evaluated_at,
        events=events,
        policy=policy,
    )
    expected_incident_type, expected_affected = _expected_incident(
        fault_case.expected_labels,
        identity_map,
    )
    payment = _provider_payment(events)
    fault = _provider_fault(case_id, payment)
    changed = (
        payment.model_copy(update={"status": PaymentStatus.FAILED, "captured": False})
        if fault is ArenaProviderFault.STATE_CHANGED_DURING_CAPTURE
        else None
    )
    provider_plan = create_provider_plan(
        case_id=case_id,
        merchant_id=merchant_id,
        account_id=f"acc_arena{merchant_index:02d}",
        initial_state=payment,
        capture_fault=fault,
        state_after_change=changed,
        duplicate_confirmation_deliveries=1 if _selector(case_id, "duplicate") % 13 == 0 else 0,
        started_at=fault_case.evaluated_at,
    )
    action_eligible = (
        expected_incident_type is IncidentType.AUTHORIZED_NOT_CAPTURED
        and expected_affected is not None
        and expected_affected.entity_id == payment.payment_id
        and policy.capture_enabled
        and payment.amount.amount_subunits <= policy.maximum_capture_subunits
    )
    recoverable = action_eligible and fault not in {
        ArenaProviderFault.REJECT_CAPTURE,
        ArenaProviderFault.STATE_CHANGED_DURING_CAPTURE,
    }
    oracle = _oracle_case(
        case_id=case_id,
        seed=fault_case.seed,
        family=family,
        expected_incident_type=expected_incident_type,
        expected_affected=expected_affected,
        payment=payment,
        action_eligible=action_eligible,
        recoverable=recoverable,
        provider_plan=provider_plan,
    )
    return ArenaEvaluationCase(observed=observed, oracle=oracle)


def _observed_case(
    *,
    case_id: str,
    merchant_id: str,
    evaluated_at: AwareDatetime,
    events: tuple[NormalizedEvent, ...],
    policy: ArenaMerchantPolicy,
) -> ArenaObservedCase:
    draft = ArenaObservedCase.model_construct(
        case_id=case_id,
        merchant_id=merchant_id,
        correlation_id=events[0].correlation_id,
        evaluated_at=evaluated_at,
        events=events,
        merchant_policy=policy,
        observed_case_sha256="0" * 64,
    )
    return ArenaObservedCase.model_validate(
        {
            **draft.model_dump(mode="json"),
            "observed_case_sha256": _model_hash(draft, exclude={"observed_case_sha256"}),
        }
    )


def _oracle_case(
    *,
    case_id: str,
    seed: int,
    family: ArenaCaseFamily,
    expected_incident_type: IncidentType | None,
    expected_affected: EntityReference | None,
    payment: ProviderPaymentState,
    action_eligible: bool,
    recoverable: bool,
    provider_plan: ArenaProviderPlan,
) -> ArenaOracleCase:
    draft = ArenaOracleCase.model_construct(
        case_id=case_id,
        seed=seed,
        family=family,
        expected_incident_type=expected_incident_type,
        expected_affected_entity=expected_affected,
        payment_amount=payment.amount,
        action_eligible=action_eligible,
        recoverable=recoverable,
        expected_action=ActionType.CAPTURE_PAYMENT if action_eligible else None,
        provider_plan=provider_plan,
        oracle_sha256="0" * 64,
    )
    return ArenaOracleCase.model_validate(
        {
            **draft.model_dump(mode="json"),
            "oracle_sha256": _model_hash(draft, exclude={"oracle_sha256"}),
        }
    )


def _merchant_policy(merchant_id: str, merchant_index: int) -> ArenaMerchantPolicy:
    maxima = (25_000, 50_000, 100_000, 250_000)
    draft = ArenaMerchantPolicy.model_construct(
        policy_version="arena-merchant-policy-v1",
        merchant_id=merchant_id,
        capture_enabled=merchant_index % 10 != 0,
        maximum_capture_subunits=maxima[merchant_index % len(maxima)],
        independent_checker_required=True,
        policy_sha256="0" * 64,
    )
    return ArenaMerchantPolicy.model_validate(
        {
            **draft.model_dump(mode="json"),
            "policy_sha256": _model_hash(draft, exclude={"policy_sha256"}),
        }
    )


def _rewrite_events(
    events: Sequence[NormalizedEvent],
    *,
    case_id: str,
    merchant_id: str,
    amount_subunits: int,
) -> tuple[tuple[NormalizedEvent, ...], dict[tuple[EntityType, str], str]]:
    identity_map = {
        (event.subject.entity_type, event.subject.entity_id): _entity_id(
            case_id,
            event.subject.entity_type,
            event.subject.entity_id,
        )
        for event in events
    }
    untyped_map = {original: rewritten for (_, original), rewritten in identity_map.items()}
    correlation_id = untyped_map.get(events[0].correlation_id) or _entity_id(
        case_id,
        EntityType.RAZORPAY_ORDER,
        events[0].correlation_id,
    )
    rewritten: list[NormalizedEvent] = []
    for event in events:
        identity = f"chakravyuh:arena:{case_id}:event:{event.event_id}"
        payload = _rewrite_payload(
            event.payload,
            subject_type=event.subject.entity_type,
            identity_map=untyped_map,
            amount_subunits=amount_subunits,
        )
        rewritten.append(
            event.model_copy(
                update={
                    "event_id": uuid5(NAMESPACE_URL, identity),
                    "merchant_id": merchant_id,
                    "source": EventSource.RAZORPAY_WEBHOOK,
                    "source_event_id": f"arena_evt_{uuid5(NAMESPACE_URL, identity).hex}",
                    "subject": event.subject.model_copy(
                        update={
                            "entity_id": identity_map[
                                (event.subject.entity_type, event.subject.entity_id)
                            ]
                        }
                    ),
                    "correlation_id": correlation_id,
                    "payload": payload,
                }
            )
        )
    return tuple(rewritten), identity_map


def _rewrite_payload(
    payload: dict[str, JsonValue],
    *,
    subject_type: EntityType,
    identity_map: dict[str, str],
    amount_subunits: int,
) -> dict[str, JsonValue]:
    rewritten = dict(payload)
    for field in ("id", "order_id", "payment_id", "invoice_id", "reference_id"):
        value = rewritten.get(field)
        if isinstance(value, str) and value in identity_map:
            rewritten[field] = identity_map[value]
    original_amount = rewritten.get("amount")
    if isinstance(original_amount, int) and not isinstance(original_amount, bool):
        rewritten["amount"] = (
            max(1, amount_subunits * original_amount // _BASE_AMOUNT_SUBUNITS)
            if subject_type is EntityType.REFUND
            else amount_subunits
        )
    for field in ("amount_paid", "amount_due", "amount_refunded"):
        value = rewritten.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            rewritten[field] = amount_subunits * value // _BASE_AMOUNT_SUBUNITS
    return rewritten


def _expected_incident(
    labels: frozenset[str],
    identity_map: dict[tuple[EntityType, str], str],
) -> tuple[IncidentType | None, EntityReference | None]:
    if not labels:
        return None, None
    if len(labels) != 1:
        msg = "arena v1 accepts exactly zero or one expected incident per case"
        raise ValueError(msg)
    incident_value, entity_type_value, entity_id = next(iter(labels)).split("|", maxsplit=2)
    entity_type = EntityType(entity_type_value)
    return IncidentType(incident_value), EntityReference(
        entity_type=entity_type,
        entity_id=identity_map[(entity_type, entity_id)],
    )


def _provider_payment(events: tuple[NormalizedEvent, ...]) -> ProviderPaymentState:
    state = reduce_payment_journey(list(events))
    payments = [
        entity
        for entity in state.entities
        if entity.entity.entity_type is EntityType.PAYMENT
        and entity.effective_payment_status is not None
        and entity.amount is not None
    ]
    if not payments:
        msg = "arena case requires one provider payment state"
        raise ValueError(msg)
    payment = max(payments, key=_payment_order)
    assert payment.effective_payment_status is not None
    assert payment.amount is not None
    status = payment.effective_payment_status
    return ProviderPaymentState(
        payment_id=payment.entity.entity_id,
        status=status,
        amount=payment.amount,
        captured=status
        in {
            PaymentStatus.CAPTURED,
            PaymentStatus.PARTIALLY_REFUNDED,
            PaymentStatus.REFUNDED,
        },
        order_id=payment.order_id,
    )


def _payment_order(payment: JourneyEntityState) -> tuple[AwareDatetime, str]:
    return payment.last_occurred_at, payment.entity.entity_id


def _provider_fault(case_id: str, payment: ProviderPaymentState) -> ArenaProviderFault:
    if payment.status is not PaymentStatus.AUTHORIZED or payment.captured:
        return ArenaProviderFault.NONE
    bucket = _selector(case_id, "provider-fault") % 100
    if bucket < 5:
        return ArenaProviderFault.REJECT_CAPTURE
    if bucket < 10:
        return ArenaProviderFault.TIMEOUT_BEFORE_MUTATION
    if bucket < 15:
        return ArenaProviderFault.TIMEOUT_AFTER_MUTATION
    if bucket < 20:
        return ArenaProviderFault.STATE_CHANGED_DURING_CAPTURE
    return ArenaProviderFault.NONE


def _amount_for_case(case_id: str) -> int:
    return _AMOUNT_LADDER_SUBUNITS[_selector(case_id, "amount") % len(_AMOUNT_LADDER_SUBUNITS)]


def _entity_id(case_id: str, entity_type: EntityType, original_id: str) -> str:
    digest = uuid5(
        NAMESPACE_URL,
        f"chakravyuh:arena:{case_id}:{entity_type.value}:{original_id}",
    ).hex[:24]
    prefix = {
        EntityType.RAZORPAY_ORDER: "order_",
        EntityType.PAYMENT: "pay_",
        EntityType.PAYMENT_LINK: "plink_",
        EntityType.REFUND: "rfnd_",
    }.get(entity_type, f"{entity_type.value}_")
    return f"{prefix}{digest}"


def _portfolio_manifest(
    contract: RecoveryArenaContract,
    *,
    dataset_role: ArenaDatasetRole,
    seed_start: int,
    seed_count: int,
    cases: tuple[ArenaEvaluationCase, ...],
) -> ArenaPortfolioManifest:
    family_counts = Counter(item.oracle.family.value for item in cases)
    fault_counts = Counter(item.oracle.provider_plan.capture_fault.value for item in cases)
    draft = ArenaPortfolioManifest.model_construct(
        portfolio_version=PORTFOLIO_VERSION,
        dataset_role=dataset_role,
        contract_sha256=contract.contract_sha256,
        seed_start=seed_start,
        seed_count=seed_count,
        case_count=len(cases),
        merchant_count=len({item.observed.merchant_id for item in cases}),
        scoring_currency=contract.scoring_currency,
        synthetic_payment_volume_subunits=sum(
            item.oracle.payment_amount.amount_subunits for item in cases
        ),
        oracle_recoverable_revenue_subunits=sum(
            item.oracle.payment_amount.amount_subunits for item in cases if item.oracle.recoverable
        ),
        family_counts=dict(sorted(family_counts.items())),
        provider_fault_counts=dict(sorted(fault_counts.items())),
        observed_cases_root_sha256=_merkle_root(
            sorted(item.observed.observed_case_sha256 for item in cases)
        ),
        oracle_cases_root_sha256=_merkle_root(sorted(item.oracle.oracle_sha256 for item in cases)),
        manifest_sha256="0" * 64,
    )
    return ArenaPortfolioManifest.model_validate(
        {
            **draft.model_dump(mode="json"),
            "manifest_sha256": _model_hash(draft, exclude={"manifest_sha256"}),
        }
    )


def _selector(identity: str, purpose: str) -> int:
    return int(hashlib.sha256(f"{purpose}:{identity}".encode()).hexdigest()[:16], 16)


def _model_hash(model: BaseModel, *, exclude: set[str]) -> str:
    return _canonical_hash(model.model_dump(mode="json", exclude=exclude))


def _merkle_root(hashes: Sequence[str]) -> str:
    if not hashes:
        msg = "arena Merkle root requires at least one leaf"
        raise ValueError(msg)
    layer = [bytes.fromhex(value) for value in hashes]
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [
            hashlib.sha256(layer[index] + layer[index + 1]).digest()
            for index in range(0, len(layer), 2)
        ]
    return layer[0].hex()


def _canonical_hash(value: object) -> str:
    body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()
