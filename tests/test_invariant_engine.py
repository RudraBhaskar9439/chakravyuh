"""Deterministic invariant rules, grace periods, evidence, and identity tests."""

from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, uuid5

import pytest

from chakravyuh.application.invariant_evaluation import (
    InvariantEvaluationBatchResult,
    ProcessInvariantEvaluationBatch,
)
from chakravyuh.domain.enums import EntityType, EventSource, IncidentType
from chakravyuh.domain.events import EntityReference, NormalizedEvent
from chakravyuh.domain.invariants import (
    DeterministicPaymentInvariantEvaluator,
    InvariantEvaluationResult,
    InvariantPolicy,
)
from chakravyuh.domain.journeys import PaymentJourneyState, reduce_payment_journey
from chakravyuh.simulation.journeys import JourneyScenario, generate_synthetic_journey


def _evaluate(
    scenario: JourneyScenario,
    *,
    after_minutes: int,
    events: tuple[NormalizedEvent, ...] | None = None,
) -> tuple[PaymentJourneyState, InvariantEvaluationResult]:
    journey = generate_synthetic_journey(scenario, seed=601)
    evidence = events or journey.events
    state = reduce_payment_journey(list(evidence))
    result = DeterministicPaymentInvariantEvaluator().evaluate(
        state,
        evidence,
        as_of=state.last_occurred_at + timedelta(minutes=after_minutes),
    )
    return state, result


@pytest.mark.parametrize(
    ("scenario", "after_minutes", "expected"),
    [
        (JourneyScenario.CAPTURED_ORDER_UNPAID, 10, IncidentType.CAPTURED_BUT_ORDER_UNPAID),
        (JourneyScenario.AUTHORIZED_NOT_CAPTURED, 20, IncidentType.AUTHORIZED_NOT_CAPTURED),
    ],
)
def test_timed_invariants_open_after_their_grace_period(
    scenario: JourneyScenario,
    after_minutes: int,
    expected: IncidentType,
) -> None:
    _, result = _evaluate(scenario, after_minutes=after_minutes)

    assert [finding.incident_type for finding in result.findings] == [expected]
    assert result.findings[0].evidence
    assert result.next_evaluation_at is None


def test_timed_invariant_schedules_without_raising_a_false_positive() -> None:
    state, result = _evaluate(JourneyScenario.AUTHORIZED_NOT_CAPTURED, after_minutes=5)

    assert result.findings == ()
    assert result.next_evaluation_at == state.last_occurred_at + timedelta(minutes=15)


def test_success_and_recovered_failure_do_not_raise_incidents() -> None:
    for scenario in (
        JourneyScenario.SUCCESSFUL_PAYMENT,
        JourneyScenario.FAILED_THEN_RECOVERED,
        JourneyScenario.PARTIALLY_REFUNDED,
        JourneyScenario.OUT_OF_ORDER_DELIVERY,
        JourneyScenario.DUPLICATE_DELIVERY,
    ):
        _, result = _evaluate(scenario, after_minutes=60)
        assert result.findings == ()


def test_failed_payment_without_a_later_capture_is_detected() -> None:
    journey = generate_synthetic_journey(JourneyScenario.FAILED_THEN_RECOVERED, seed=602)
    failed_only = journey.events[:2]
    _, result = _evaluate(
        JourneyScenario.FAILED_THEN_RECOVERED,
        after_minutes=31,
        events=failed_only,
    )

    assert [finding.incident_type for finding in result.findings] == [
        IncidentType.FAILED_WITHOUT_RECOVERY
    ]


def test_terminal_event_regression_is_detected_without_waiting() -> None:
    journey = generate_synthetic_journey(JourneyScenario.SUCCESSFUL_PAYMENT, seed=603)
    captured = journey.events[2]
    regression = captured.model_copy(
        update={
            "event_id": uuid5(NAMESPACE_URL, "phase-6-regression"),
            "source_event_id": "phase-6-regression",
            "event_type": "payment.failed",
            "occurred_at": captured.occurred_at + timedelta(minutes=1),
            "observed_at": captured.observed_at + timedelta(minutes=1),
            "payload": {**captured.payload, "status": "failed"},
        }
    )
    evidence = (*journey.events[:3], regression)
    _, result = _evaluate(
        JourneyScenario.SUCCESSFUL_PAYMENT,
        after_minutes=1,
        events=evidence,
    )

    assert [finding.incident_type for finding in result.findings] == [
        IncidentType.EVENT_ORDER_CORRUPTION
    ]
    assert len(result.findings[0].evidence) == 2


def _payment_link_event(
    base: NormalizedEvent,
    *,
    link_id: str,
    minute: int,
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=uuid5(NAMESPACE_URL, f"phase-6:{link_id}"),
        merchant_id=base.merchant_id,
        source=EventSource.SIMULATOR,
        source_event_id=f"sim-{link_id}",
        event_type="payment_link.issued",
        subject=EntityReference(entity_type=EntityType.PAYMENT_LINK, entity_id=link_id),
        occurred_at=base.occurred_at + timedelta(minutes=minute),
        observed_at=base.observed_at + timedelta(minutes=minute),
        correlation_id=base.correlation_id,
        payload={
            "id": link_id,
            "status": "issued",
            "order_id": base.correlation_id,
            "amount": 10_000,
            "currency": "INR",
        },
    )


def test_paid_order_with_active_recovery_link_is_stale_after_grace() -> None:
    journey = generate_synthetic_journey(JourneyScenario.SUCCESSFUL_PAYMENT, seed=604)
    link = _payment_link_event(journey.events[0], link_id="plink-stale", minute=2)
    evidence = (*journey.events, link)
    _, result = _evaluate(
        JourneyScenario.SUCCESSFUL_PAYMENT,
        after_minutes=10,
        events=evidence,
    )

    assert [finding.incident_type for finding in result.findings] == [
        IncidentType.STALE_RECOVERY_AFTER_SUCCESS
    ]


def test_duplicate_active_recovery_links_have_one_stable_finding() -> None:
    journey = generate_synthetic_journey(JourneyScenario.AUTHORIZED_NOT_CAPTURED, seed=605)
    evidence = (
        *journey.events,
        _payment_link_event(journey.events[0], link_id="plink-a", minute=2),
        _payment_link_event(journey.events[0], link_id="plink-b", minute=3),
    )
    _, first = _evaluate(
        JourneyScenario.AUTHORIZED_NOT_CAPTURED,
        after_minutes=1,
        events=evidence,
    )
    _, second = _evaluate(
        JourneyScenario.AUTHORIZED_NOT_CAPTURED,
        after_minutes=2,
        events=tuple(reversed(evidence)),
    )

    assert [finding.incident_type for finding in first.findings] == [
        IncidentType.DUPLICATE_ACTIVE_RECOVERY_LINKS
    ]
    assert first.findings[0].incident_key == second.findings[0].incident_key
    assert first.findings[0].finding_hash == second.findings[0].finding_hash


def test_policy_version_changes_with_reviewed_thresholds() -> None:
    default = InvariantPolicy()
    changed = InvariantPolicy(authorized_capture_grace_seconds=901)

    assert default.version == InvariantPolicy().version
    assert default.version != changed.version


async def test_application_batch_delegates_bounded_inputs() -> None:
    repository = AsyncMock()
    expected = InvariantEvaluationBatchResult(claimed=2, completed=1, dead_lettered=1)
    repository.process_batch.return_value = expected
    evaluator = DeterministicPaymentInvariantEvaluator()

    result = await ProcessInvariantEvaluationBatch(
        repository,
        evaluator,
        worker_id="invariant-worker-1",
        batch_size=20,
        max_events_per_journey=1_000,
    ).execute()

    assert result is expected
    repository.process_batch.assert_awaited_once_with(
        evaluator=evaluator,
        worker_id="invariant-worker-1",
        batch_size=20,
        max_events_per_journey=1_000,
    )
