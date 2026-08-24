"""Seeded, deterministic payment journeys with known temporal outcomes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from chakravyuh.domain.enums import EntityType, EventSource, PaymentStatus
from chakravyuh.domain.events import EntityReference, NormalizedEvent


class JourneyScenario(StrEnum):
    SUCCESSFUL_PAYMENT = "successful_payment"
    AUTHORIZED_NOT_CAPTURED = "authorized_not_captured"
    CAPTURED_ORDER_UNPAID = "captured_order_unpaid"
    FAILED_THEN_RECOVERED = "failed_then_recovered"
    PARTIALLY_REFUNDED = "partially_refunded"
    OUT_OF_ORDER_DELIVERY = "out_of_order_delivery"
    DUPLICATE_DELIVERY = "duplicate_delivery"


class SyntheticJourney(BaseModel):
    """A deterministic event delivery with an explicit expected payment outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario: JourneyScenario
    seed: int = Field(ge=0)
    merchant_id: str = Field(min_length=1, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=255)
    expected_payment_status: PaymentStatus
    events: tuple[NormalizedEvent, ...]


def generate_synthetic_journey(
    scenario: JourneyScenario,
    *,
    seed: int,
    merchant_id: str = "merchant-simulator",
    start_at: datetime | None = None,
) -> SyntheticJourney:
    """Generate stable identities and delivery order for one named scenario."""

    if seed < 0:
        msg = "seed must be non-negative"
        raise ValueError(msg)
    started = start_at or datetime(2026, 1, 1, tzinfo=UTC)
    if started.tzinfo is None or started.utcoffset() is None:
        msg = "start_at must be timezone-aware"
        raise ValueError(msg)

    order_id = _provider_id("order", seed)
    payment_id = _provider_id("pay", seed)
    retry_payment_id = _provider_id("pay_retry", seed)
    refund_id = _provider_id("rfnd", seed)
    correlation_id = order_id
    specs = _scenario_specs(
        scenario,
        order_id=order_id,
        payment_id=payment_id,
        retry_payment_id=retry_payment_id,
        refund_id=refund_id,
    )
    if scenario is JourneyScenario.OUT_OF_ORDER_DELIVERY:
        specs = [specs[0], *reversed(specs[1:])]

    events = tuple(
        _event(
            scenario=scenario,
            seed=seed,
            merchant_id=merchant_id,
            correlation_id=correlation_id,
            started=started,
            delivery_index=delivery_index,
            spec=spec,
        )
        for delivery_index, spec in enumerate(specs)
    )
    if scenario is JourneyScenario.DUPLICATE_DELIVERY:
        events = (*events, events[-1])
    return SyntheticJourney(
        scenario=scenario,
        seed=seed,
        merchant_id=merchant_id,
        correlation_id=correlation_id,
        expected_payment_status=_expected_status(scenario),
        events=events,
    )


def _scenario_specs(
    scenario: JourneyScenario,
    *,
    order_id: str,
    payment_id: str,
    retry_payment_id: str,
    refund_id: str,
) -> list[tuple[int, str, EntityType, str, dict[str, object]]]:
    order_created = (
        0,
        "order.created",
        EntityType.RAZORPAY_ORDER,
        order_id,
        {
            "id": order_id,
            "status": "created",
            "amount": 10_000,
            "amount_paid": 0,
            "amount_due": 10_000,
            "currency": "INR",
        },
    )
    authorized = _payment_spec(1, "authorized", payment_id, order_id)
    captured = _payment_spec(2, "captured", payment_id, order_id)
    order_paid = (
        3,
        "order.paid",
        EntityType.RAZORPAY_ORDER,
        order_id,
        {
            "id": order_id,
            "status": "paid",
            "amount": 10_000,
            "amount_paid": 10_000,
            "amount_due": 0,
            "currency": "INR",
        },
    )
    if scenario is JourneyScenario.AUTHORIZED_NOT_CAPTURED:
        return [order_created, authorized]
    if scenario is JourneyScenario.CAPTURED_ORDER_UNPAID:
        return [order_created, authorized, captured]
    if scenario is JourneyScenario.FAILED_THEN_RECOVERED:
        failed = _payment_spec(1, "failed", payment_id, order_id)
        retry_authorized = _payment_spec(2, "authorized", retry_payment_id, order_id)
        retry_captured = _payment_spec(3, "captured", retry_payment_id, order_id)
        return [order_created, failed, retry_authorized, retry_captured, _shift(order_paid, 4)]
    successful = [order_created, authorized, captured, order_paid]
    if scenario is JourneyScenario.PARTIALLY_REFUNDED:
        refund = (
            4,
            "refund.processed",
            EntityType.REFUND,
            refund_id,
            {
                "id": refund_id,
                "status": "processed",
                "payment_id": payment_id,
                "amount": 2_500,
                "currency": "INR",
            },
        )
        return [*successful, refund]
    return successful


def _payment_spec(
    minute: int,
    status: str,
    payment_id: str,
    order_id: str,
) -> tuple[int, str, EntityType, str, dict[str, object]]:
    return (
        minute,
        f"payment.{status}",
        EntityType.PAYMENT,
        payment_id,
        {
            "id": payment_id,
            "status": status,
            "order_id": order_id,
            "amount": 10_000,
            "amount_refunded": 0,
            "currency": "INR",
        },
    )


def _shift(
    spec: tuple[int, str, EntityType, str, dict[str, object]],
    minute: int,
) -> tuple[int, str, EntityType, str, dict[str, object]]:
    return (minute, *spec[1:])


def _event(
    *,
    scenario: JourneyScenario,
    seed: int,
    merchant_id: str,
    correlation_id: str,
    started: datetime,
    delivery_index: int,
    spec: tuple[int, str, EntityType, str, dict[str, object]],
) -> NormalizedEvent:
    minute, event_type, entity_type, entity_id, payload = spec
    identity = f"{scenario.value}:{seed}:{event_type}:{entity_id}"
    return NormalizedEvent(
        event_id=uuid5(NAMESPACE_URL, f"chakravyuh:simulation:event:{identity}"),
        merchant_id=merchant_id,
        source=EventSource.SIMULATOR,
        source_event_id=f"sim_{uuid5(NAMESPACE_URL, identity).hex}",
        event_type=event_type,
        subject=EntityReference(entity_type=entity_type, entity_id=entity_id),
        occurred_at=started + timedelta(minutes=minute),
        observed_at=started + timedelta(hours=1, seconds=delivery_index),
        correlation_id=correlation_id,
        payload=payload,
    )


def _provider_id(prefix: str, seed: int) -> str:
    return f"{prefix}_{uuid5(NAMESPACE_URL, f'chakravyuh:simulation:{seed}:{prefix}').hex[:18]}"


def _expected_status(scenario: JourneyScenario) -> PaymentStatus:
    if scenario is JourneyScenario.AUTHORIZED_NOT_CAPTURED:
        return PaymentStatus.AUTHORIZED
    if scenario is JourneyScenario.FAILED_THEN_RECOVERED:
        return PaymentStatus.CAPTURED
    if scenario is JourneyScenario.PARTIALLY_REFUNDED:
        return PaymentStatus.PARTIALLY_REFUNDED
    return PaymentStatus.CAPTURED
