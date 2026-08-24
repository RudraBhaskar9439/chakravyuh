"""End-to-end HTTP boundary tests for Razorpay webhook intake."""

import hmac
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from chakravyuh.api.main import create_app
from chakravyuh.config import Settings
from chakravyuh.domain.errors import EventIdentityConflictError
from chakravyuh.domain.webhooks import RawWebhookEvent


class MemoryWebhookStore:
    def __init__(self) -> None:
        self.events: dict[tuple[str, str], RawWebhookEvent] = {}

    async def append(self, event: RawWebhookEvent) -> bool:
        key = (event.merchant_id, event.source_event_id)
        existing = self.events.get(key)
        if existing is None:
            self.events[key] = event
            return True
        if existing.body_sha256 != event.body_sha256:
            raise EventIdentityConflictError
        return False

    async def get(self, merchant_id: str, source_event_id: str) -> RawWebhookEvent | None:
        return self.events.get((merchant_id, source_event_id))


class ConflictingWebhookStore(MemoryWebhookStore):
    async def append(self, event: RawWebhookEvent) -> bool:
        raise EventIdentityConflictError


@pytest.fixture
def webhook_body() -> bytes:
    payload: dict[str, Any] = {
        "entity": "event",
        "account_id": "acc_test",
        "event": "payment.captured",
        "contains": ["payment"],
        "created_at": 1_787_571_200,
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test",
                    "entity": "payment",
                    "amount": 100,
                    "currency": "INR",
                    "status": "captured",
                }
            }
        },
        "future_addition": "accepted",
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "log_level": "CRITICAL",
        "razorpay_merchant_id": "merchant-1",
        "razorpay_account_id": "acc_test",
        "razorpay_webhook_secret": "test-webhook-secret",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, "sha256").hexdigest()


def _headers(body: bytes, **overrides: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": _signature(body, "test-webhook-secret"),
        "X-Razorpay-Event-Id": "provider-event-1",
    }
    headers.update(overrides)
    return headers


async def _client(
    store: MemoryWebhookStore,
    settings: Settings | None = None,
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings or _settings(), webhook_event_store=store)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_webhook_commits_before_acknowledgement_and_deduplicates(
    webhook_body: bytes,
) -> None:
    store = MemoryWebhookStore()
    async for client in _client(store):
        first = await client.post(
            "/v1/webhooks/razorpay/merchant-1",
            content=webhook_body,
            headers=_headers(webhook_body),
        )
        duplicate = await client.post(
            "/v1/webhooks/razorpay/merchant-1",
            content=webhook_body,
            headers=_headers(webhook_body),
        )

    assert first.status_code == 202
    assert first.json()["accepted"] is True
    assert duplicate.status_code == 200
    assert duplicate.json() == {"event_id": first.json()["event_id"], "accepted": False}
    assert next(iter(store.events.values())).raw_body == webhook_body


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        (
            {
                "Content-Type": "text/plain",
                "X-Razorpay-Event-Id": "provider-event-1",
                "X-Razorpay-Signature": "00" * 32,
            },
            415,
        ),
        ({"Content-Type": "application/json"}, 400),
        (
            {
                "Content-Type": "application/json",
                "X-Razorpay-Event-Id": "provider-event-1",
                "X-Razorpay-Signature": "00" * 32,
            },
            401,
        ),
    ],
)
async def test_webhook_rejects_invalid_transport(
    webhook_body: bytes,
    headers: dict[str, str],
    expected_status: int,
) -> None:
    async for client in _client(MemoryWebhookStore()):
        response = await client.post(
            "/v1/webhooks/razorpay/merchant-1",
            content=webhook_body,
            headers=headers,
        )
    assert response.status_code == expected_status


async def test_webhook_rejects_authenticated_invalid_json() -> None:
    body = b"not-json"
    async for client in _client(MemoryWebhookStore()):
        response = await client.post(
            "/v1/webhooks/razorpay/merchant-1",
            content=body,
            headers=_headers(body),
        )
    assert response.status_code == 400


async def test_webhook_rejects_unsafe_provider_event_identity(webhook_body: bytes) -> None:
    headers = _headers(webhook_body, **{"X-Razorpay-Event-Id": "unsafe event id"})
    async for client in _client(MemoryWebhookStore()):
        response = await client.post(
            "/v1/webhooks/razorpay/merchant-1",
            content=webhook_body,
            headers=headers,
        )
    assert response.status_code == 400


async def test_webhook_rejects_unknown_merchant_and_account(webhook_body: bytes) -> None:
    async for client in _client(MemoryWebhookStore()):
        unknown_merchant = await client.post(
            "/v1/webhooks/razorpay/unknown",
            content=webhook_body,
            headers=_headers(webhook_body),
        )
    async for client in _client(MemoryWebhookStore(), _settings(razorpay_account_id="other")):
        wrong_account = await client.post(
            "/v1/webhooks/razorpay/merchant-1",
            content=webhook_body,
            headers=_headers(webhook_body),
        )
    assert unknown_merchant.status_code == 404
    assert wrong_account.status_code == 403


async def test_webhook_fails_closed_when_not_configured(webhook_body: bytes) -> None:
    async for client in _client(MemoryWebhookStore(), Settings(environment="test")):
        response = await client.post(
            "/v1/webhooks/razorpay/merchant-1",
            content=webhook_body,
            headers=_headers(webhook_body),
        )
    assert response.status_code == 503


async def test_webhook_enforces_streaming_body_limit() -> None:
    body = json.dumps({"padding": "x" * 2_000}).encode()
    async for client in _client(MemoryWebhookStore(), _settings(max_webhook_body_bytes=1_024)):
        response = await client.post(
            "/v1/webhooks/razorpay/merchant-1",
            content=body,
            headers=_headers(body),
        )
    assert response.status_code == 413


async def test_webhook_surfaces_identity_conflict(webhook_body: bytes) -> None:
    async for client in _client(ConflictingWebhookStore()):
        response = await client.post(
            "/v1/webhooks/razorpay/merchant-1",
            content=webhook_body,
            headers=_headers(webhook_body),
        )
    assert response.status_code == 409
