"""Pure tests for deterministic Razorpay normalization."""

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from chakravyuh.domain.enums import EntityType, EventSource
from chakravyuh.domain.errors import NormalizationError, NormalizationErrorCode
from chakravyuh.domain.webhooks import RawWebhookEvent
from chakravyuh.infrastructure.razorpay.normalizer import RazorpayWebhookNormalizer


def _raw_event(
    event_type: str,
    *,
    entity: dict[str, object] | None = None,
    related: dict[str, object] | None = None,
    source: EventSource = EventSource.RAZORPAY_WEBHOOK,
) -> RawWebhookEvent:
    family = event_type.partition(".")[0]
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    provider_payload: dict[str, object] = {}
    if entity is not None:
        provider_payload[family] = {"entity": entity}
    if related:
        provider_payload.update(related)
    payload = {"event": event_type, "payload": provider_payload}
    return RawWebhookEvent(
        event_id=uuid4(),
        merchant_id="merchant-1",
        source=source,
        source_event_id="provider-event-1",
        event_type=event_type,
        occurred_at=now,
        observed_at=now + timedelta(seconds=1),
        payload=payload,
        raw_body=b"{}",
    )


@pytest.mark.parametrize(
    ("event_type", "entity_id", "entity_type"),
    [
        ("payment.captured", "pay_1", EntityType.PAYMENT),
        ("order.paid", "order_1", EntityType.RAZORPAY_ORDER),
        ("refund.processed", "rfnd_1", EntityType.REFUND),
        ("payment_link.paid", "plink_1", EntityType.PAYMENT_LINK),
    ],
)
def test_normalizer_selects_primary_entity_from_event_family(
    event_type: str,
    entity_id: str,
    entity_type: EntityType,
) -> None:
    raw = _raw_event(event_type, entity={"id": entity_id, "status": "captured"})

    normalized = RazorpayWebhookNormalizer().normalize(raw)

    assert normalized.subject.entity_type is entity_type
    assert normalized.subject.entity_id == entity_id
    assert normalized.payload == {"id": entity_id, "status": "captured"}
    assert normalized.source_event_id == raw.source_event_id


def test_normalizer_is_deterministic_and_prefers_provider_correlation() -> None:
    raw = _raw_event(
        "payment.captured",
        entity={"id": "pay_1", "order_id": "order_1"},
    )
    normalizer = RazorpayWebhookNormalizer()

    first = normalizer.normalize(raw)
    second = normalizer.normalize(raw)

    assert first == second
    assert first.event_id == uuid5(NAMESPACE_URL, f"chakravyuh:normalized:{raw.event_id}")
    assert first.correlation_id == "order_1"


def test_normalizer_accepts_authoritative_razorpay_api_fallback() -> None:
    raw = _raw_event(
        "payment.authorized",
        entity={"id": "pay_1", "order_id": "order_1", "status": "authorized"},
        source=EventSource.RAZORPAY_API,
    )

    normalized = RazorpayWebhookNormalizer().normalize(raw)

    assert normalized.source is EventSource.RAZORPAY_API
    assert normalized.subject.entity_id == "pay_1"
    assert normalized.correlation_id == "order_1"


def test_normalizer_uses_related_order_for_payment_link_correlation() -> None:
    raw = _raw_event(
        "payment_link.paid",
        entity={"id": "plink_1"},
        related={"order": {"entity": {"id": "order_1"}}},
    )

    assert RazorpayWebhookNormalizer().normalize(raw).correlation_id == "order_1"


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (
            _raw_event(
                "payment.captured",
                entity={"id": "pay_1"},
                source=EventSource.SIMULATOR,
            ),
            NormalizationErrorCode.UNSUPPORTED_SOURCE,
        ),
        (
            _raw_event("subscription.charged", entity={"id": "sub_1"}),
            NormalizationErrorCode.UNSUPPORTED_EVENT_TYPE,
        ),
        (
            _raw_event("payment.captured"),
            NormalizationErrorCode.MISSING_PRIMARY_ENTITY,
        ),
        (
            _raw_event("payment.captured", entity={"status": "captured"}),
            NormalizationErrorCode.MISSING_ENTITY_ID,
        ),
    ],
)
def test_normalizer_returns_stable_sanitized_failures(
    raw: RawWebhookEvent,
    code: NormalizationErrorCode,
) -> None:
    with pytest.raises(NormalizationError) as failure:
        RazorpayWebhookNormalizer().normalize(raw)

    assert failure.value.code is code
    assert str(failure.value) == code.value


def test_normalizer_rejects_provider_time_after_observation() -> None:
    raw = _raw_event("payment.captured", entity={"id": "pay_1"})
    raw = raw.model_copy(update={"occurred_at": raw.observed_at + timedelta(seconds=1)})

    with pytest.raises(NormalizationError) as failure:
        RazorpayWebhookNormalizer().normalize(raw)

    assert failure.value.code is NormalizationErrorCode.EVENT_TIME_AFTER_OBSERVATION
