"""Held-out deterministic fault injection and honest invariant metrics."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from chakravyuh.application.ports import InvariantEvaluator
from chakravyuh.domain.enums import EntityType, EventSource, IncidentType
from chakravyuh.domain.events import EntityReference, NormalizedEvent
from chakravyuh.domain.invariants import InvariantFinding
from chakravyuh.domain.journeys import reduce_payment_journey
from chakravyuh.simulation.journeys import JourneyScenario, generate_synthetic_journey

FALSE_POSITIVE_REVIEW_COST_SUBUNITS = 2_000


@dataclass(frozen=True, slots=True)
class FaultCase:
    """One labelled journey used only for evaluation, never for training."""

    case_id: str
    seed: int
    events: tuple[NormalizedEvent, ...]
    evaluated_at: datetime
    expected_labels: frozenset[str]


class FaultEvaluationMetrics(BaseModel):
    """Aggregate held-out classification and operator-cost metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_role: str = "held_out_synthetic"
    decision_authority: str = "deterministic_rules_only"
    case_count: int = Field(ge=1)
    expected_finding_count: int = Field(ge=0)
    predicted_finding_count: int = Field(ge=0)
    true_positive_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    false_positive_review_cost_subunits: int = Field(ge=0)
    false_positive_review_cost_currency: str = "INR"


def generate_fault_set(seeds: Iterable[int]) -> tuple[FaultCase, ...]:
    """Generate positive and adversarial negative cases from unseen seed identities."""

    cases: list[FaultCase] = []
    seen_seeds: set[int] = set()
    for seed in seeds:
        if seed < 0:
            msg = "fault-set seeds must be non-negative"
            raise ValueError(msg)
        if seed in seen_seeds:
            msg = "fault-set seeds must be unique"
            raise ValueError(msg)
        seen_seeds.add(seed)
        cases.extend(_cases_for_seed(seed))
    if not cases:
        msg = "at least one fault-set seed is required"
        raise ValueError(msg)
    return tuple(cases)


def evaluate_fault_set(
    cases: Sequence[FaultCase],
    evaluator: InvariantEvaluator,
    *,
    false_positive_review_cost_subunits: int = FALSE_POSITIVE_REVIEW_COST_SUBUNITS,
) -> FaultEvaluationMetrics:
    """Run the pure evaluator and score exact incident/entity labels."""

    if not cases:
        msg = "at least one fault case is required"
        raise ValueError(msg)
    if false_positive_review_cost_subunits < 0:
        msg = "false-positive review cost must be non-negative"
        raise ValueError(msg)
    true_positive_count = 0
    false_positive_count = 0
    false_negative_count = 0
    expected_finding_count = 0
    predicted_finding_count = 0
    for case in cases:
        state = reduce_payment_journey(list(case.events))
        result = evaluator.evaluate(state, case.events, as_of=case.evaluated_at)
        predicted = frozenset(_finding_label(finding) for finding in result.findings)
        expected = case.expected_labels
        true_positive_count += len(predicted & expected)
        false_positive_count += len(predicted - expected)
        false_negative_count += len(expected - predicted)
        expected_finding_count += len(expected)
        predicted_finding_count += len(predicted)

    precision = _safe_ratio(
        true_positive_count,
        true_positive_count + false_positive_count,
    )
    recall = _safe_ratio(
        true_positive_count,
        true_positive_count + false_negative_count,
    )
    f1 = _safe_ratio(2 * precision * recall, precision + recall)
    return FaultEvaluationMetrics(
        case_count=len(cases),
        expected_finding_count=expected_finding_count,
        predicted_finding_count=predicted_finding_count,
        true_positive_count=true_positive_count,
        false_positive_count=false_positive_count,
        false_negative_count=false_negative_count,
        precision=precision,
        recall=recall,
        f1=f1,
        false_positive_review_cost_subunits=(
            false_positive_count * false_positive_review_cost_subunits
        ),
    )


def _cases_for_seed(seed: int) -> list[FaultCase]:
    started = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=seed % 300)
    captured_unpaid = generate_synthetic_journey(
        JourneyScenario.CAPTURED_ORDER_UNPAID,
        seed=seed,
        start_at=started,
    )
    authorized = generate_synthetic_journey(
        JourneyScenario.AUTHORIZED_NOT_CAPTURED,
        seed=seed,
        start_at=started,
    )
    recovering = generate_synthetic_journey(
        JourneyScenario.FAILED_THEN_RECOVERED,
        seed=seed,
        start_at=started,
    )
    successful = generate_synthetic_journey(
        JourneyScenario.SUCCESSFUL_PAYMENT,
        seed=seed,
        start_at=started,
    )
    failed_only = recovering.events[:2]
    regression = _regression_event(successful.events[2], seed=seed)
    regressed = (*successful.events[:3], regression)
    active_link = _payment_link_event(
        successful.events[0],
        seed=seed,
        suffix="stale",
        minute=5,
        status="issued",
    )
    stale = (*successful.events, active_link)
    duplicate = (
        *authorized.events,
        _payment_link_event(
            authorized.events[0],
            seed=seed,
            suffix="duplicate-a",
            minute=2,
            status="active",
        ),
        _payment_link_event(
            authorized.events[0],
            seed=seed,
            suffix="duplicate-b",
            minute=3,
            status="active",
        ),
    )

    positives = [
        _case(
            "captured-order-unpaid",
            seed,
            captured_unpaid.events,
            after=timedelta(minutes=10),
            incident_type=IncidentType.CAPTURED_BUT_ORDER_UNPAID,
            affected=captured_unpaid.events[2].subject,
        ),
        _case(
            "authorized-not-captured",
            seed,
            authorized.events,
            after=timedelta(minutes=20),
            incident_type=IncidentType.AUTHORIZED_NOT_CAPTURED,
            affected=authorized.events[1].subject,
        ),
        _case(
            "failed-without-recovery",
            seed,
            failed_only,
            after=timedelta(minutes=31),
            incident_type=IncidentType.FAILED_WITHOUT_RECOVERY,
            affected=failed_only[1].subject,
        ),
        _case(
            "stale-recovery-link",
            seed,
            stale,
            after=timedelta(minutes=10),
            incident_type=IncidentType.STALE_RECOVERY_AFTER_SUCCESS,
            affected=active_link.subject,
        ),
        _case(
            "duplicate-recovery-links",
            seed,
            duplicate,
            after=timedelta(minutes=1),
            incident_type=IncidentType.DUPLICATE_ACTIVE_RECOVERY_LINKS,
            affected=duplicate[-2].subject,
        ),
        _case(
            "terminal-regression",
            seed,
            regressed,
            after=timedelta(minutes=1),
            incident_type=IncidentType.EVENT_ORDER_CORRUPTION,
            affected=regression.subject,
        ),
    ]
    negatives = [
        _negative_case(scenario.value, seed, scenario_events, after=timedelta(minutes=60))
        for scenario, scenario_events in (
            (
                JourneyScenario.SUCCESSFUL_PAYMENT,
                successful.events,
            ),
            (
                JourneyScenario.FAILED_THEN_RECOVERED,
                recovering.events,
            ),
            (
                JourneyScenario.PARTIALLY_REFUNDED,
                generate_synthetic_journey(
                    JourneyScenario.PARTIALLY_REFUNDED,
                    seed=seed,
                    start_at=started,
                ).events,
            ),
            (
                JourneyScenario.OUT_OF_ORDER_DELIVERY,
                generate_synthetic_journey(
                    JourneyScenario.OUT_OF_ORDER_DELIVERY,
                    seed=seed,
                    start_at=started,
                ).events,
            ),
            (
                JourneyScenario.DUPLICATE_DELIVERY,
                generate_synthetic_journey(
                    JourneyScenario.DUPLICATE_DELIVERY,
                    seed=seed,
                    start_at=started,
                ).events,
            ),
        )
    ]
    negatives.extend(
        (
            _negative_case(
                "captured-unpaid-within-grace",
                seed,
                captured_unpaid.events,
                after=timedelta(minutes=1),
            ),
            _negative_case(
                "authorized-within-grace",
                seed,
                authorized.events,
                after=timedelta(minutes=5),
            ),
            _negative_case(
                "single-active-link-before-payment",
                seed,
                (*authorized.events, duplicate[-2]),
                after=timedelta(minutes=1),
            ),
            _negative_case(
                "inactive-link-after-success",
                seed,
                (
                    *successful.events,
                    _payment_link_event(
                        successful.events[0],
                        seed=seed,
                        suffix="cancelled",
                        minute=5,
                        status="cancelled",
                    ),
                ),
                after=timedelta(minutes=60),
            ),
        )
    )
    return [*positives, *negatives]


def _case(
    name: str,
    seed: int,
    events: tuple[NormalizedEvent, ...],
    *,
    after: timedelta,
    incident_type: IncidentType,
    affected: EntityReference,
) -> FaultCase:
    return FaultCase(
        case_id=f"{name}:{seed}",
        seed=seed,
        events=events,
        evaluated_at=max(event.occurred_at for event in events) + after,
        expected_labels=frozenset({_label(incident_type, affected)}),
    )


def _negative_case(
    name: str,
    seed: int,
    events: tuple[NormalizedEvent, ...],
    *,
    after: timedelta,
) -> FaultCase:
    return FaultCase(
        case_id=f"{name}:{seed}",
        seed=seed,
        events=events,
        evaluated_at=max(event.occurred_at for event in events) + after,
        expected_labels=frozenset(),
    )


def _payment_link_event(
    base: NormalizedEvent,
    *,
    seed: int,
    suffix: str,
    minute: int,
    status: str,
) -> NormalizedEvent:
    link_id = f"plink_{seed}_{suffix}"
    identity = f"fault-link:{seed}:{suffix}"
    return NormalizedEvent(
        event_id=uuid5(NAMESPACE_URL, identity),
        merchant_id=base.merchant_id,
        source=EventSource.SIMULATOR,
        source_event_id=f"sim_{uuid5(NAMESPACE_URL, identity).hex}",
        event_type=f"payment_link.{status}",
        subject=EntityReference(entity_type=EntityType.PAYMENT_LINK, entity_id=link_id),
        occurred_at=base.occurred_at + timedelta(minutes=minute),
        observed_at=base.observed_at + timedelta(minutes=minute),
        correlation_id=base.correlation_id,
        payload={
            "id": link_id,
            "status": status,
            "order_id": base.correlation_id,
            "amount": 10_000,
            "currency": "INR",
        },
    )


def _regression_event(captured: NormalizedEvent, *, seed: int) -> NormalizedEvent:
    identity = f"fault-regression:{seed}"
    return captured.model_copy(
        update={
            "event_id": uuid5(NAMESPACE_URL, identity),
            "source_event_id": f"sim_{uuid5(NAMESPACE_URL, identity).hex}",
            "event_type": "payment.failed",
            "occurred_at": captured.occurred_at + timedelta(minutes=1),
            "observed_at": captured.observed_at + timedelta(minutes=1),
            "payload": {**captured.payload, "status": "failed"},
        }
    )


def _finding_label(finding: InvariantFinding) -> str:
    return _label(finding.incident_type, finding.affected_entity)


def _label(incident_type: IncidentType, affected: EntityReference) -> str:
    return "|".join(
        (
            incident_type.value,
            affected.entity_type.value,
            affected.entity_id,
        )
    )


def _safe_ratio(numerator: float, denominator: float) -> float:
    return 1.0 if denominator == 0 else numerator / denominator
