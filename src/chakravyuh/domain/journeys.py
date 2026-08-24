"""Deterministic temporal reduction of normalized payment-journey events."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from chakravyuh.domain.enums import (
    EntityType,
    JourneyRelationshipType,
    PaymentStatus,
)
from chakravyuh.domain.events import EntityReference, NormalizedEvent
from chakravyuh.domain.money import Money

TEMPORAL_REDUCER_VERSION = "payment-journey-v1"


class JourneyRelationship(BaseModel):
    """A provider-neutral edge inferred only from explicit provider references."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_type: JourneyRelationshipType
    source: EntityReference
    target: EntityReference


class JourneyEntityState(BaseModel):
    """Latest temporal state and stable identity of one journey entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity: EntityReference
    provider_status: str | None = Field(default=None, max_length=64)
    effective_payment_status: PaymentStatus | None = None
    amount: Money | None = None
    amount_paid_subunits: int | None = Field(default=None, ge=0)
    amount_due_subunits: int | None = Field(default=None, ge=0)
    amount_refunded_subunits: int | None = Field(default=None, ge=0)
    order_id: str | None = Field(default=None, max_length=255)
    payment_id: str | None = Field(default=None, max_length=255)
    reference_id: str | None = Field(default=None, max_length=255)
    first_occurred_at: AwareDatetime
    last_occurred_at: AwareDatetime
    latest_event_id: UUID
    event_count: int = Field(ge=1)


class PaymentJourneyState(BaseModel):
    """Replayable current state for one merchant correlation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    merchant_id: str = Field(min_length=1, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=255)
    event_count: int = Field(ge=1)
    first_occurred_at: AwareDatetime
    last_occurred_at: AwareDatetime
    latest_event_id: UUID
    entities: tuple[JourneyEntityState, ...]
    relationships: tuple[JourneyRelationship, ...] = ()


class TemporalPaymentJourneyReducer:
    """Versioned adapter around the pure reduction function."""

    version = TEMPORAL_REDUCER_VERSION

    def reduce(self, events: list[NormalizedEvent]) -> PaymentJourneyState:
        return reduce_payment_journey(events)


@dataclass(slots=True)
class _MutableEntity:
    entity: EntityReference
    provider_status: str | None
    amount: Money | None
    amount_paid_subunits: int | None
    amount_due_subunits: int | None
    amount_refunded_subunits: int | None
    order_id: str | None
    payment_id: str | None
    reference_id: str | None
    first_occurred_at: datetime
    last_occurred_at: datetime
    latest_event_id: UUID
    event_count: int


def reduce_payment_journey(events: list[NormalizedEvent]) -> PaymentJourneyState:
    """Reduce one correlation independently of caller-provided delivery order."""

    ordered = _unique_ordered(events)
    first = ordered[0]
    for event in ordered[1:]:
        if event.merchant_id != first.merchant_id or event.correlation_id != first.correlation_id:
            msg = "all events must belong to one merchant correlation"
            raise ValueError(msg)

    entities: dict[tuple[EntityType, str], _MutableEntity] = {}
    for event in ordered:
        key = (event.subject.entity_type, event.subject.entity_id)
        existing = entities.get(key)
        snapshot = _snapshot(event, existing)
        entities[key] = snapshot

    processed_refunds: dict[str, int] = {}
    for entity in entities.values():
        if (
            entity.entity.entity_type is EntityType.REFUND
            and entity.provider_status == "processed"
            and entity.payment_id is not None
            and entity.amount is not None
        ):
            processed_refunds[entity.payment_id] = (
                processed_refunds.get(entity.payment_id, 0) + entity.amount.amount_subunits
            )

    immutable_entities = tuple(
        _freeze_entity(entity, processed_refunds)
        for entity in sorted(
            entities.values(),
            key=lambda item: (item.entity.entity_type.value, item.entity.entity_id),
        )
    )
    relationships = _relationships(immutable_entities)
    return PaymentJourneyState(
        merchant_id=first.merchant_id,
        correlation_id=first.correlation_id,
        event_count=len(ordered),
        first_occurred_at=ordered[0].occurred_at,
        last_occurred_at=ordered[-1].occurred_at,
        latest_event_id=ordered[-1].event_id,
        entities=immutable_entities,
        relationships=relationships,
    )


def journey_state_hash(state: PaymentJourneyState) -> str:
    """Return a canonical content hash independent of Python object ordering."""

    canonical = json.dumps(
        state.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _unique_ordered(events: list[NormalizedEvent]) -> list[NormalizedEvent]:
    if not events:
        msg = "at least one event is required"
        raise ValueError(msg)
    unique: dict[UUID, NormalizedEvent] = {}
    for event in events:
        existing = unique.get(event.event_id)
        if existing is not None and existing != event:
            msg = "one event_id cannot identify conflicting event content"
            raise ValueError(msg)
        unique[event.event_id] = event
    return sorted(unique.values(), key=_temporal_order)


def _temporal_order(event: NormalizedEvent) -> tuple[datetime, datetime, str, str, str]:
    return (
        event.occurred_at,
        event.observed_at,
        event.event_type,
        event.source_event_id,
        event.event_id.hex,
    )


def _snapshot(
    event: NormalizedEvent,
    existing: _MutableEntity | None,
) -> _MutableEntity:
    payload = event.payload
    provider_status = (
        _bounded_text(payload.get("status"), 64) or event.event_type.rpartition(".")[2]
    )
    currency = _currency(payload.get("currency"))
    amount_subunits = _nonnegative_int(payload.get("amount"))
    amount = (
        Money(amount_subunits=amount_subunits, currency=currency)
        if amount_subunits is not None and currency is not None
        else None
    )
    if existing is None:
        return _MutableEntity(
            entity=event.subject,
            provider_status=provider_status,
            amount=amount,
            amount_paid_subunits=_nonnegative_int(payload.get("amount_paid")),
            amount_due_subunits=_nonnegative_int(payload.get("amount_due")),
            amount_refunded_subunits=_nonnegative_int(payload.get("amount_refunded")),
            order_id=_bounded_text(payload.get("order_id"), 255),
            payment_id=_bounded_text(payload.get("payment_id"), 255),
            reference_id=_bounded_text(payload.get("reference_id"), 255),
            first_occurred_at=event.occurred_at,
            last_occurred_at=event.occurred_at,
            latest_event_id=event.event_id,
            event_count=1,
        )
    existing.provider_status = provider_status or existing.provider_status
    existing.amount = amount or existing.amount
    existing.amount_paid_subunits = _prefer_int(
        payload.get("amount_paid"), existing.amount_paid_subunits
    )
    existing.amount_due_subunits = _prefer_int(
        payload.get("amount_due"), existing.amount_due_subunits
    )
    existing.amount_refunded_subunits = _prefer_int(
        payload.get("amount_refunded"), existing.amount_refunded_subunits
    )
    existing.order_id = _bounded_text(payload.get("order_id"), 255) or existing.order_id
    existing.payment_id = _bounded_text(payload.get("payment_id"), 255) or existing.payment_id
    existing.reference_id = _bounded_text(payload.get("reference_id"), 255) or existing.reference_id
    existing.last_occurred_at = event.occurred_at
    existing.latest_event_id = event.event_id
    existing.event_count += 1
    return existing


def _freeze_entity(
    entity: _MutableEntity,
    processed_refunds: dict[str, int],
) -> JourneyEntityState:
    effective_status: PaymentStatus | None = None
    refunded = entity.amount_refunded_subunits
    if entity.entity.entity_type is EntityType.PAYMENT:
        refunded = max(refunded or 0, processed_refunds.get(entity.entity.entity_id, 0))
        effective_status = _effective_payment_status(
            entity.provider_status, entity.amount, refunded
        )
    return JourneyEntityState(
        entity=entity.entity,
        provider_status=entity.provider_status,
        effective_payment_status=effective_status,
        amount=entity.amount,
        amount_paid_subunits=entity.amount_paid_subunits,
        amount_due_subunits=entity.amount_due_subunits,
        amount_refunded_subunits=refunded,
        order_id=entity.order_id,
        payment_id=entity.payment_id,
        reference_id=entity.reference_id,
        first_occurred_at=entity.first_occurred_at,
        last_occurred_at=entity.last_occurred_at,
        latest_event_id=entity.latest_event_id,
        event_count=entity.event_count,
    )


def _effective_payment_status(
    provider_status: str | None,
    amount: Money | None,
    refunded_subunits: int,
) -> PaymentStatus | None:
    if provider_status is None:
        return None
    try:
        status = PaymentStatus(provider_status)
    except ValueError:
        return None
    if status not in {
        PaymentStatus.CAPTURED,
        PaymentStatus.PARTIALLY_REFUNDED,
        PaymentStatus.REFUNDED,
    }:
        return status
    if refunded_subunits == 0:
        return status
    if amount is not None and refunded_subunits >= amount.amount_subunits:
        return PaymentStatus.REFUNDED
    return PaymentStatus.PARTIALLY_REFUNDED


def _relationships(entities: tuple[JourneyEntityState, ...]) -> tuple[JourneyRelationship, ...]:
    relationships: set[tuple[JourneyRelationshipType, EntityType, str, EntityType, str]] = set()
    for state in entities:
        entity = state.entity
        if entity.entity_type is EntityType.PAYMENT and state.order_id is not None:
            relationships.add(
                (
                    JourneyRelationshipType.PAYMENT_FOR_ORDER,
                    entity.entity_type,
                    entity.entity_id,
                    EntityType.RAZORPAY_ORDER,
                    state.order_id,
                )
            )
        elif entity.entity_type is EntityType.REFUND and state.payment_id is not None:
            relationships.add(
                (
                    JourneyRelationshipType.REFUND_FOR_PAYMENT,
                    entity.entity_type,
                    entity.entity_id,
                    EntityType.PAYMENT,
                    state.payment_id,
                )
            )
        elif entity.entity_type is EntityType.PAYMENT_LINK and state.order_id is not None:
            relationships.add(
                (
                    JourneyRelationshipType.PAYMENT_LINK_FOR_ORDER,
                    entity.entity_type,
                    entity.entity_id,
                    EntityType.RAZORPAY_ORDER,
                    state.order_id,
                )
            )
    return tuple(
        JourneyRelationship(
            relationship_type=relationship_type,
            source=EntityReference(entity_type=source_type, entity_id=source_id),
            target=EntityReference(entity_type=target_type, entity_id=target_id),
        )
        for relationship_type, source_type, source_id, target_type, target_id in sorted(
            relationships,
            key=lambda item: tuple(str(value) for value in item),
        )
    )


def _bounded_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized and len(normalized) <= maximum else None


def _currency(value: object) -> str | None:
    currency = _bounded_text(value, 3)
    if currency is None or len(currency) != 3 or not currency.isalpha():
        return None
    return currency.upper()


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _prefer_int(value: object, existing: int | None) -> int | None:
    candidate = _nonnegative_int(value)
    return candidate if candidate is not None else existing
