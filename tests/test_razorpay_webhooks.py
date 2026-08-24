"""Provider authentication and envelope-decoding tests."""

import hmac
import json
from datetime import UTC, datetime

import pytest

from chakravyuh.infrastructure.razorpay.webhooks import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    decode_webhook,
    verify_webhook_signature,
)


def _signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, "sha256").hexdigest()


def test_signature_uses_exact_raw_bytes_and_supports_rotation() -> None:
    body = b'{"entity":"event"}'
    verify_webhook_signature(body, _signature(body, "old-secret"), ("new-secret", "old-secret"))

    with pytest.raises(InvalidWebhookSignatureError):
        verify_webhook_signature(body + b"\n", _signature(body, "old-secret"), ("old-secret",))


@pytest.mark.parametrize("signature", [None, "not-hex", "00"])
def test_signature_rejects_missing_or_malformed_values(signature: str | None) -> None:
    with pytest.raises(InvalidWebhookSignatureError):
        verify_webhook_signature(b"{}", signature, ("secret",))


def test_signature_rejects_empty_secret_set() -> None:
    with pytest.raises(InvalidWebhookSignatureError):
        verify_webhook_signature(b"{}", "00" * 32, ())
    with pytest.raises(InvalidWebhookSignatureError):
        verify_webhook_signature(b"{}", "00" * 32, ("",))


def test_decode_retains_exact_body_and_additive_fields() -> None:
    webhook_body = json.dumps(
        {
            "entity": "event",
            "event": "payment.captured",
            "account_id": "acc_test",
            "created_at": 1_787_571_200,
            "payload": {},
            "future_addition": "accepted",
        },
        separators=(",", ":"),
    ).encode()
    observed_at = datetime(2026, 8, 24, 12, tzinfo=UTC)

    event = decode_webhook(
        merchant_id="merchant-1",
        source_event_id="provider-event-1",
        raw_body=webhook_body,
        observed_at=observed_at,
    )

    assert event.raw_body == webhook_body
    assert event.body_sha256
    assert event.event_type == "payment.captured"
    assert event.account_id == "acc_test"
    assert event.observed_at == observed_at
    assert event.payload["future_addition"] == "accepted"


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"[]",
        b'{"entity":"event"}',
        b'{"entity":"wrong","event":"payment.captured","created_at":1,"payload":{}}',
        b'{"entity":"event","event":"PAYMENT CAPTURED","created_at":1,"payload":{}}',
        b'{"entity":"event","event":"payment.captured","created_at":999999999999999999,"payload":{}}',
    ],
)
def test_decode_rejects_invalid_envelopes(body: bytes) -> None:
    with pytest.raises(InvalidWebhookPayloadError):
        decode_webhook(
            merchant_id="merchant-1",
            source_event_id="provider-event-1",
            raw_body=body,
            observed_at=datetime.now(UTC),
        )
