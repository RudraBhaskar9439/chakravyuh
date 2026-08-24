"""Deterministic correctness, chaos, policy, and throughput proof pack."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from time import perf_counter, perf_counter_ns
from uuid import NAMESPACE_URL, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from chakravyuh.domain.action_policy import DeterministicRecoveryPolicy, RecoveryPolicyConfig
from chakravyuh.domain.actions import ActionProposal, create_action_proposal
from chakravyuh.domain.enums import (
    ActionRisk,
    ActionType,
    EntityType,
    IncidentType,
    PolicyOutcome,
)
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.invariants import DeterministicPaymentInvariantEvaluator, InvariantPolicy
from chakravyuh.domain.journeys import journey_state_hash, reduce_payment_journey
from chakravyuh.domain.money import Money
from chakravyuh.simulation.faults import (
    FaultEvaluationMetrics,
    evaluate_fault_set,
    generate_fault_set,
)
from chakravyuh.simulation.journeys import JourneyScenario, generate_synthetic_journey

PROOF_VERSION = "judge-proof-v1"


class ReliabilityCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    passed: bool
    expected: str
    observed: str


class LoadMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sample_count: int = Field(ge=1)
    p50_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    maximum_latency_ms: float = Field(ge=0)
    cases_per_second: float = Field(ge=0)
    latency_budget_ms: float = Field(gt=0)
    minimum_cases_per_second: float = Field(gt=0)
    slo_passed: bool


class ReliabilityReport(BaseModel):
    """Machine-readable judge artifact with a stable proof digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proof_version: str = PROOF_VERSION
    generated_at: AwareDatetime
    evaluator_version: str
    seed_start: int = Field(ge=0)
    seed_count: int = Field(ge=1)
    invariant_metrics: FaultEvaluationMetrics
    load_metrics: LoadMetrics
    chaos_checks: tuple[ReliabilityCheck, ...]
    recovery_policy_checks: tuple[ReliabilityCheck, ...]
    proof_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool


def run_reliability_evaluation(
    *,
    seed_start: int = 50_000,
    seed_count: int = 100,
    latency_budget_ms: float = 50,
    minimum_cases_per_second: float = 100,
) -> ReliabilityReport:
    if seed_start < 0 or seed_count < 1 or seed_count > 10_000:
        msg = "seed_start must be non-negative and seed_count must be 1..10000"
        raise ValueError(msg)
    if latency_budget_ms <= 0 or minimum_cases_per_second <= 0:
        msg = "load SLO bounds must be positive"
        raise ValueError(msg)

    cases = generate_fault_set(range(seed_start, seed_start + seed_count))
    evaluator = DeterministicPaymentInvariantEvaluator(InvariantPolicy())
    latencies_ms: list[float] = []
    started = perf_counter()
    for case in cases:
        case_started = perf_counter_ns()
        state = reduce_payment_journey(list(case.events))
        evaluator.evaluate(state, case.events, as_of=case.evaluated_at)
        latencies_ms.append((perf_counter_ns() - case_started) / 1_000_000)
    elapsed = max(perf_counter() - started, 1e-9)

    metrics = evaluate_fault_set(cases, evaluator)
    ordered_latencies = sorted(latencies_ms)
    load = LoadMetrics(
        sample_count=len(cases),
        p50_latency_ms=_percentile(ordered_latencies, 0.50),
        p95_latency_ms=_percentile(ordered_latencies, 0.95),
        maximum_latency_ms=ordered_latencies[-1],
        cases_per_second=len(cases) / elapsed,
        latency_budget_ms=latency_budget_ms,
        minimum_cases_per_second=minimum_cases_per_second,
        slo_passed=(
            _percentile(ordered_latencies, 0.95) <= latency_budget_ms
            and len(cases) / elapsed >= minimum_cases_per_second
        ),
    )
    chaos_checks = _chaos_checks(seed_start)
    policy_checks = _policy_checks()
    correctness_passed = metrics.false_positive_count == metrics.false_negative_count == 0
    passed = (
        correctness_passed
        and load.slo_passed
        and all(check.passed for check in (*chaos_checks, *policy_checks))
    )
    proof_document = {
        "chaos_checks": [check.model_dump(mode="json") for check in chaos_checks],
        "evaluator_version": evaluator.version,
        "invariant_metrics": metrics.model_dump(mode="json"),
        "proof_version": PROOF_VERSION,
        "recovery_policy_checks": [check.model_dump(mode="json") for check in policy_checks],
        "seed_count": seed_count,
        "seed_start": seed_start,
    }
    return ReliabilityReport(
        generated_at=datetime.now(UTC),
        evaluator_version=evaluator.version,
        seed_start=seed_start,
        seed_count=seed_count,
        invariant_metrics=metrics,
        load_metrics=load,
        chaos_checks=chaos_checks,
        recovery_policy_checks=policy_checks,
        proof_sha256=_canonical_hash(proof_document),
        passed=passed,
    )


def _chaos_checks(seed: int) -> tuple[ReliabilityCheck, ...]:
    duplicate = generate_synthetic_journey(JourneyScenario.DUPLICATE_DELIVERY, seed=seed)
    unique_events = tuple(dict.fromkeys(event.event_id for event in duplicate.events))
    event_by_id = {event.event_id: event for event in duplicate.events}
    duplicate_hash = journey_state_hash(reduce_payment_journey(list(duplicate.events)))
    unique_hash = journey_state_hash(
        reduce_payment_journey([event_by_id[event_id] for event_id in unique_events])
    )

    reordered = generate_synthetic_journey(JourneyScenario.OUT_OF_ORDER_DELIVERY, seed=seed + 1)
    delivered_hash = journey_state_hash(reduce_payment_journey(list(reordered.events)))
    chronological_hash = journey_state_hash(
        reduce_payment_journey(sorted(reordered.events, key=lambda event: event.occurred_at))
    )
    return (
        ReliabilityCheck(
            name="duplicate_delivery_is_idempotent",
            passed=duplicate_hash == unique_hash,
            expected=unique_hash,
            observed=duplicate_hash,
        ),
        ReliabilityCheck(
            name="out_of_order_delivery_is_deterministic",
            passed=delivered_hash == chronological_hash,
            expected=chronological_hash,
            observed=delivered_hash,
        ),
    )


def _policy_checks() -> tuple[ReliabilityCheck, ...]:
    safe_policy = DeterministicRecoveryPolicy(
        RecoveryPolicyConfig(
            actions_enabled=True,
            test_credentials=True,
            merchant_id="merchant-judge",
            maximum_capture_subunits=1_000_000,
            minimum_capture_confidence=0.9,
        )
    )
    safe = safe_policy.evaluate(_capture_proposal(amount_subunits=10_000, confidence=0.97))
    oversized = safe_policy.evaluate(_capture_proposal(amount_subunits=1_000_001, confidence=0.97))
    low_confidence = safe_policy.evaluate(_capture_proposal(amount_subunits=10_000, confidence=0.2))
    killed = DeterministicRecoveryPolicy(
        RecoveryPolicyConfig(
            actions_enabled=False,
            test_credentials=True,
            merchant_id="merchant-judge",
        )
    ).evaluate(_capture_proposal(amount_subunits=10_000, confidence=0.97))
    return (
        _policy_check(
            "exact_test_capture_requires_checker",
            safe.outcome,
            PolicyOutcome.REQUIRE_APPROVAL,
        ),
        _policy_check("oversized_capture_denied", oversized.outcome, PolicyOutcome.DENY),
        _policy_check("low_confidence_capture_denied", low_confidence.outcome, PolicyOutcome.DENY),
        _policy_check("kill_switch_denies_capture", killed.outcome, PolicyOutcome.DENY),
    )


def _capture_proposal(*, amount_subunits: int, confidence: float) -> ActionProposal:
    proposed_at = datetime(2026, 8, 24, 12, tzinfo=UTC)
    identity = f"{amount_subunits}:{confidence}"
    return create_action_proposal(
        proposal_id=uuid5(NAMESPACE_URL, f"chakravyuh:judge:proposal:{identity}"),
        incident_id=uuid5(NAMESPACE_URL, "chakravyuh:judge:incident"),
        source_revision_id=uuid5(NAMESPACE_URL, "chakravyuh:judge:revision"),
        diagnosis_id=uuid5(NAMESPACE_URL, "chakravyuh:judge:diagnosis"),
        merchant_id="merchant-judge",
        incident_type=IncidentType.AUTHORIZED_NOT_CAPTURED,
        action_type=ActionType.CAPTURE_PAYMENT,
        risk=ActionRisk.MONEY_MOVEMENT,
        target=EntityReference(entity_type=EntityType.PAYMENT, entity_id="pay_judgeproof"),
        amount=Money(amount_subunits=amount_subunits, currency="INR"),
        rationale="Exact authorization remains open beyond the capture window.",
        evidence_ids=("invariant:authorization-open", "event:payment-authorized"),
        confidence=confidence,
        idempotency_key=_canonical_hash({"identity": identity}),
        proposed_by="judge-demo-maker",
        request_id="judge-demo-request",
        proposed_at=proposed_at,
        expires_at=proposed_at + timedelta(minutes=15),
    )


def _policy_check(
    name: str,
    observed: PolicyOutcome,
    expected: PolicyOutcome,
) -> ReliabilityCheck:
    return ReliabilityCheck(
        name=name,
        passed=observed is expected,
        expected=expected.value,
        observed=observed.value,
    )


def _percentile(values: list[float], percentile: float) -> float:
    index = max(0, math.ceil(percentile * len(values)) - 1)
    return values[index]


def _canonical_hash(value: object) -> str:
    body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()
