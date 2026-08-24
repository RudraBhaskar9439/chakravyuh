"""Razorpay webhook authentication and provider-envelope decoding."""

import hmac
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from chakravyuh.domain.enums import EventSource
from chakravyuh.domain.webhooks import RawWebhookEvent


class InvalidWebhookSignatureError(ValueError):
    """The supplied signature is missing, malformed, or does not authenticate."""


class InvalidWebhookPayloadError(ValueError):
    """The authenticated body is not a supported Razorpay event envelope."""


class RazorpayWebhookEnvelope(BaseModel):
    """Minimum stable fields needed from a Razorpay event.

    Unknown fields are retained in the raw ledger and tolerated here so additive
    provider changes do not take down the webhook endpoint.
    """

    model_config = ConfigDict(extra="allow")

    entity: Literal["event"]
    event: str = Field(min_length=1, max_length=255, pattern=r"^[a-z][a-z0-9_.-]*$")
    account_id: str | None = Field(default=None, min_length=1, max_length=255)
    created_at: Annotated[int, Field(ge=0)]
    contains: tuple[str, ...] = ()
    payload: dict[str, JsonValue]


_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def verify_webhook_signature(
    raw_body: bytes,
    signature: str | None,
    secrets: tuple[str, ...],
) -> None:
    """Authenticate exact request bytes against every active rotation secret."""
    if signature is None or not secrets or any(not secret for secret in secrets):
        raise InvalidWebhookSignatureError

    try:
        received = bytes.fromhex(signature)
    except ValueError as error:
        raise InvalidWebhookSignatureError from error
    if len(received) != 32:
        raise InvalidWebhookSignatureError

    authenticated = False
    for secret in secrets:
        expected = hmac.digest(secret.encode(), raw_body, "sha256")
        authenticated |= hmac.compare_digest(expected, received)
    if not authenticated:
        raise InvalidWebhookSignatureError


def decode_webhook(
    *,
    merchant_id: str,
    source_event_id: str,
    raw_body: bytes,
    observed_at: datetime,
) -> RawWebhookEvent:
    """Decode an authenticated event while retaining the exact signed bytes."""
    try:
        payload = _JSON_OBJECT.validate_json(raw_body)
        envelope = RazorpayWebhookEnvelope.model_validate(payload)
        occurred_at = datetime.fromtimestamp(envelope.created_at, tz=UTC)
    except (OSError, OverflowError, ValidationError, ValueError) as error:
        raise InvalidWebhookPayloadError from error

    return RawWebhookEvent(
        merchant_id=merchant_id,
        source=EventSource.RAZORPAY_WEBHOOK,
        source_event_id=source_event_id,
        event_type=envelope.event,
        account_id=envelope.account_id,
        occurred_at=occurred_at,
        observed_at=observed_at,
        payload=payload,
        raw_body=raw_body,
    )
