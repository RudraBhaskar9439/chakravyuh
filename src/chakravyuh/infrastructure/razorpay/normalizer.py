"""Deterministic Razorpay webhook-to-domain normalization."""

from collections.abc import Mapping
from typing import Final
from uuid import NAMESPACE_URL, uuid5

from pydantic import JsonValue

from chakravyuh.application.ports import WebhookNormalizer
from chakravyuh.domain.enums import EntityType, EventSource
from chakravyuh.domain.errors import NormalizationError, NormalizationErrorCode
from chakravyuh.domain.events import EntityReference, NormalizedEvent
from chakravyuh.domain.webhooks import RawWebhookEvent

NORMALIZER_VERSION: Final = "razorpay-webhook-v1"

_PRIMARY_ENTITY_TYPES: Final[dict[str, EntityType]] = {
    "order": EntityType.RAZORPAY_ORDER,
    "payment": EntityType.PAYMENT,
    "payment_link": EntityType.PAYMENT_LINK,
    "refund": EntityType.REFUND,
}
_CORRELATION_FIELDS: Final = ("order_id", "payment_id", "invoice_id", "reference_id")


class RazorpayWebhookNormalizer(WebhookNormalizer):
    """Normalize supported money-journey snapshots without external I/O."""

    version = NORMALIZER_VERSION

    def normalize(self, event: RawWebhookEvent) -> NormalizedEvent:
        if event.source is not EventSource.RAZORPAY_WEBHOOK:
            raise NormalizationError(NormalizationErrorCode.UNSUPPORTED_SOURCE)
        if event.occurred_at > event.observed_at:
            raise NormalizationError(NormalizationErrorCode.EVENT_TIME_AFTER_OBSERVATION)

        event_family = event.event_type.partition(".")[0]
        entity_type = _PRIMARY_ENTITY_TYPES.get(event_family)
        if entity_type is None:
            raise NormalizationError(NormalizationErrorCode.UNSUPPORTED_EVENT_TYPE)

        provider_payload = _mapping(event.payload.get("payload"))
        wrapper = _mapping(provider_payload.get(event_family))
        entity = _mapping(wrapper.get("entity"))
        if not entity:
            raise NormalizationError(NormalizationErrorCode.MISSING_PRIMARY_ENTITY)

        entity_id = entity.get("id")
        if not isinstance(entity_id, str) or not entity_id.strip() or len(entity_id) > 255:
            raise NormalizationError(NormalizationErrorCode.MISSING_ENTITY_ID)

        return NormalizedEvent(
            event_id=uuid5(NAMESPACE_URL, f"chakravyuh:normalized:{event.event_id}"),
            merchant_id=event.merchant_id,
            source=event.source,
            source_event_id=event.source_event_id,
            event_type=event.event_type,
            subject=EntityReference(entity_type=entity_type, entity_id=entity_id),
            occurred_at=event.occurred_at,
            observed_at=event.observed_at,
            correlation_id=_correlation_id(entity, provider_payload, entity_id),
            payload=dict(entity),
        )


def _mapping(value: JsonValue | None) -> Mapping[str, JsonValue]:
    if isinstance(value, dict):
        return value
    return {}


def _correlation_id(
    primary: Mapping[str, JsonValue],
    provider_payload: Mapping[str, JsonValue],
    fallback: str,
) -> str:
    for field in _CORRELATION_FIELDS:
        candidate = primary.get(field)
        if isinstance(candidate, str) and candidate.strip() and len(candidate) <= 255:
            return candidate

    order_wrapper = _mapping(provider_payload.get("order"))
    order = _mapping(order_wrapper.get("entity"))
    order_id = order.get("id")
    if isinstance(order_id, str) and order_id.strip() and len(order_id) <= 255:
        return order_id
    return fallback
