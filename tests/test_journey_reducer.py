"""Pure temporal-reducer proofs."""

from datetime import UTC, datetime, timedelta

import pytest

from chakravyuh.domain.enums import EntityType, JourneyRelationshipType, PaymentStatus
from chakravyuh.domain.journeys import journey_state_hash, reduce_payment_journey
from chakravyuh.simulation.journeys import JourneyScenario, generate_synthetic_journey


def _entity(state, entity_type: EntityType):  # type: ignore[no-untyped-def]
    return next(item for item in state.entities if item.entity.entity_type is entity_type)


@pytest.mark.parametrize("scenario", list(JourneyScenario))
def test_every_synthetic_scenario_is_repeatable_and_matches_expected_status(
    scenario: JourneyScenario,
) -> None:
    first = generate_synthetic_journey(scenario, seed=42)
    second = generate_synthetic_journey(scenario, seed=42)

    assert first == second
    state = reduce_payment_journey(list(first.events))
    payments = [
        entity for entity in state.entities if entity.entity.entity_type is EntityType.PAYMENT
    ]
    assert any(
        payment.effective_payment_status is first.expected_payment_status for payment in payments
    )


def test_reducer_is_independent_of_delivery_order_and_hashes_canonical_state() -> None:
    journey = generate_synthetic_journey(JourneyScenario.SUCCESSFUL_PAYMENT, seed=7)

    forward = reduce_payment_journey(list(journey.events))
    reverse = reduce_payment_journey(list(reversed(journey.events)))

    assert forward == reverse
    assert journey_state_hash(forward) == journey_state_hash(reverse)
    assert forward.event_count == 4
    assert _entity(forward, EntityType.PAYMENT).effective_payment_status is PaymentStatus.CAPTURED


def test_duplicate_delivery_is_idempotent() -> None:
    duplicated = generate_synthetic_journey(JourneyScenario.DUPLICATE_DELIVERY, seed=8)

    state = reduce_payment_journey(list(duplicated.events))

    assert len(duplicated.events) == 5
    assert state.event_count == 4
    assert _entity(state, EntityType.PAYMENT).event_count == 2


def test_processed_refund_derives_partial_refund_and_explicit_edge() -> None:
    journey = generate_synthetic_journey(JourneyScenario.PARTIALLY_REFUNDED, seed=9)

    state = reduce_payment_journey(list(journey.events))
    payment = _entity(state, EntityType.PAYMENT)

    assert payment.amount_refunded_subunits == 2_500
    assert payment.effective_payment_status is PaymentStatus.PARTIALLY_REFUNDED
    assert any(
        relationship.relationship_type is JourneyRelationshipType.REFUND_FOR_PAYMENT
        for relationship in state.relationships
    )
    assert any(
        relationship.relationship_type is JourneyRelationshipType.PAYMENT_FOR_ORDER
        for relationship in state.relationships
    )


def test_latest_snapshot_merges_missing_optional_fields() -> None:
    journey = generate_synthetic_journey(JourneyScenario.SUCCESSFUL_PAYMENT, seed=10)
    payment_events = [event for event in journey.events if event.event_type.startswith("payment.")]
    captured = payment_events[-1].model_copy(update={"payload": {"status": "captured"}})

    state = reduce_payment_journey([payment_events[0], captured])
    payment = _entity(state, EntityType.PAYMENT)

    assert payment.provider_status == "captured"
    assert payment.amount is not None
    assert payment.amount.amount_subunits == 10_000
    assert payment.order_id == journey.correlation_id


def test_unknown_provider_status_is_preserved_without_guessing() -> None:
    journey = generate_synthetic_journey(JourneyScenario.SUCCESSFUL_PAYMENT, seed=11)
    payment = next(event for event in journey.events if event.event_type == "payment.captured")
    future = payment.model_copy(
        update={
            "event_type": "payment.future_state",
            "payload": {**payment.payload, "status": "future_state"},
        }
    )

    state = reduce_payment_journey([future])
    entity = _entity(state, EntityType.PAYMENT)

    assert entity.provider_status == "future_state"
    assert entity.effective_payment_status is None


def test_reducer_rejects_empty_mixed_or_conflicting_identity_inputs() -> None:
    with pytest.raises(ValueError, match="at least one"):
        reduce_payment_journey([])

    journey = generate_synthetic_journey(JourneyScenario.SUCCESSFUL_PAYMENT, seed=12)
    mixed = journey.events[1].model_copy(update={"merchant_id": "another-merchant"})
    with pytest.raises(ValueError, match="one merchant correlation"):
        reduce_payment_journey([journey.events[0], mixed])

    conflict = journey.events[0].model_copy(update={"event_type": "order.paid"})
    with pytest.raises(ValueError, match="conflicting event content"):
        reduce_payment_journey([journey.events[0], conflict])


def test_equal_event_times_have_a_stable_tie_breaker() -> None:
    journey = generate_synthetic_journey(JourneyScenario.SUCCESSFUL_PAYMENT, seed=13)
    payment_events = [event for event in journey.events if event.event_type.startswith("payment.")]
    same_time = datetime(2026, 1, 1, 12, tzinfo=UTC)
    authorized = payment_events[0].model_copy(
        update={"occurred_at": same_time, "observed_at": same_time + timedelta(seconds=1)}
    )
    captured = payment_events[1].model_copy(
        update={"occurred_at": same_time, "observed_at": same_time + timedelta(seconds=2)}
    )

    assert reduce_payment_journey([captured, authorized]) == reduce_payment_journey(
        [authorized, captured]
    )


def test_generator_validates_seed_and_time() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        generate_synthetic_journey(JourneyScenario.SUCCESSFUL_PAYMENT, seed=-1)
    with pytest.raises(ValueError, match="timezone-aware"):
        generate_synthetic_journey(
            JourneyScenario.SUCCESSFUL_PAYMENT,
            seed=1,
            start_at=datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
        )
