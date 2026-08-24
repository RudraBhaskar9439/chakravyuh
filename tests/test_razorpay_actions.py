"""Razorpay Test Mode adapter contract and failure-sanitization tests."""

import base64
import json

import httpx
import pytest
from pydantic import SecretStr

from chakravyuh.config import Settings
from chakravyuh.domain.enums import PaymentStatus
from chakravyuh.domain.errors import ActionControlErrorCode, RazorpayActionError
from chakravyuh.domain.money import Money
from chakravyuh.infrastructure.razorpay.actions import RazorpayTestModePaymentGateway


def _settings() -> Settings:
    return Settings(
        environment="test",
        razorpay_actions_enabled=True,
        razorpay_key_id="rzp_test_contract",
        razorpay_key_secret=SecretStr("test-secret"),
        razorpay_merchant_id="merchant-test",
    )


async def test_adapter_fetches_allowlisted_state_with_basic_auth() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "pay_123",
                "entity": "payment",
                "amount": 10_000,
                "currency": "INR",
                "status": "authorized",
                "captured": False,
                "order_id": "order_123",
                "email": "must-not-cross-boundary@example.test",
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.razorpay.com",
    )
    gateway = RazorpayTestModePaymentGateway(_settings(), client=client)
    state = await gateway.fetch_payment("pay_123")
    await client.aclose()

    assert state.status is PaymentStatus.AUTHORIZED
    assert state.amount == Money(amount_subunits=10_000, currency="INR")
    assert state.model_dump().keys() == {
        "payment_id",
        "status",
        "amount",
        "captured",
        "order_id",
    }
    expected = base64.b64encode(b"rzp_test_contract:test-secret").decode()
    assert requests[0].headers["authorization"] == f"Basic {expected}"
    assert requests[0].url.path == "/v1/payments/pay_123"


async def test_adapter_captures_exact_amount_and_validates_terminal_state() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "pay_123",
                "entity": "payment",
                "amount": 10_000,
                "currency": "INR",
                "status": "captured",
                "captured": True,
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.razorpay.com",
    )
    gateway = RazorpayTestModePaymentGateway(_settings(), client=client)
    state = await gateway.capture_payment(
        "pay_123",
        Money(amount_subunits=10_000, currency="INR"),
    )
    await client.aclose()

    assert state.captured
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/v1/payments/pay_123/capture"
    assert json.loads(requests[0].content) == {"amount": 10_000, "currency": "INR"}


@pytest.mark.parametrize(
    ("status_code", "code", "retryable"),
    [
        (400, ActionControlErrorCode.PROVIDER_REJECTED, False),
        (401, ActionControlErrorCode.PROVIDER_REJECTED, False),
        (429, ActionControlErrorCode.PROVIDER_UNAVAILABLE, True),
        (503, ActionControlErrorCode.PROVIDER_UNAVAILABLE, True),
    ],
)
async def test_adapter_maps_http_failures_without_leaking_provider_payload(
    status_code: int,
    code: ActionControlErrorCode,
    retryable: bool,
) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status_code, json={"error": {"secret": "do-not-leak"}})
        ),
        base_url="https://api.razorpay.com",
    )
    gateway = RazorpayTestModePaymentGateway(_settings(), client=client)

    with pytest.raises(RazorpayActionError) as captured:
        await gateway.fetch_payment("pay_123")
    await client.aclose()

    assert captured.value.code is code
    assert captured.value.retryable is retryable
    assert "do-not-leak" not in str(captured.value)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "id": "pay_other",
            "entity": "payment",
            "amount": 1,
            "currency": "INR",
            "status": "captured",
            "captured": True,
        },
        {
            "id": "pay_123",
            "entity": "refund",
            "amount": 1,
            "currency": "INR",
            "status": "captured",
            "captured": True,
        },
        {
            "id": "pay_123",
            "entity": "payment",
            "amount": -1,
            "currency": "INR",
            "status": "captured",
            "captured": True,
        },
    ],
)
async def test_adapter_rejects_untrusted_or_mismatched_response(payload: dict[str, object]) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        base_url="https://api.razorpay.com",
    )
    gateway = RazorpayTestModePaymentGateway(_settings(), client=client)

    with pytest.raises(RazorpayActionError) as captured:
        await gateway.fetch_payment("pay_123")
    await client.aclose()

    assert captured.value.code is ActionControlErrorCode.PROVIDER_INVALID_RESPONSE


async def test_adapter_rejects_path_injection_before_network_call() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.razorpay.com",
    )
    gateway = RazorpayTestModePaymentGateway(_settings(), client=client)

    with pytest.raises(RazorpayActionError):
        await gateway.fetch_payment("../payments/pay_123")
    await client.aclose()

    assert not called
