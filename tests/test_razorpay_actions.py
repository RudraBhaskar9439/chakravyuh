"""Razorpay Test Mode adapter contract and failure-sanitization tests."""

import base64
import hmac
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


async def test_adapter_creates_bounded_payment_link_without_customer_notification() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "plink_123",
                "entity": "payment_link",
                "amount": 10_000,
                "amount_paid": 0,
                "currency": "INR",
                "status": "created",
                "short_url": "https://rzp.io/i/test123",
                "reference_id": "chkr_123",
                "customer": {"email": "must-not-cross-boundary@example.test"},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.razorpay.com",
    )
    gateway = RazorpayTestModePaymentGateway(_settings(), client=client)
    state = await gateway.create_payment_link(
        amount=Money(amount_subunits=10_000, currency="INR"),
        reference_id="chkr_123",
        description="Recovery for a failed Test Mode payment",
    )
    await client.aclose()

    assert state.payment_link_id == "plink_123"
    assert state.short_url == "https://rzp.io/i/test123"
    payload = json.loads(requests[0].content)
    assert requests[0].url.path == "/v1/payment_links"
    assert payload["notify"] == {"sms": False, "email": False}
    assert payload["accept_partial"] is False
    assert "customer" not in state.model_dump()


async def test_adapter_creates_manual_order_and_verifies_checkout_signature() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "order_123",
                "entity": "order",
                "amount": 1_000,
                "currency": "INR",
                "receipt": "chkr-contract",
                "status": "created",
                "created_at": 1_787_571_200,
                "notes": {"ignored": "at-boundary"},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.razorpay.com",
    )
    gateway = RazorpayTestModePaymentGateway(_settings(), client=client)
    order = await gateway.create_manual_capture_order(
        amount=Money(amount_subunits=1_000, currency="INR"),
        receipt="chkr-contract",
    )
    signature = hmac.digest(b"test-secret", b"order_123|pay_123", "sha256").hex()

    assert order.order_id == "order_123"
    assert gateway.verify_checkout_signature(
        order_id="order_123",
        payment_id="pay_123",
        signature=signature,
    )
    assert not gateway.verify_checkout_signature(
        order_id="order_123",
        payment_id="pay_123",
        signature="0" * 64,
    )
    assert requests[0].url.path == "/v1/orders"
    assert json.loads(requests[0].content) == {
        "amount": 1_000,
        "currency": "INR",
        "receipt": "chkr-contract",
        "capture": "manual",
        "notes": {"source": "chakravyuh-buildathon"},
    }
    await client.aclose()


async def test_adapter_falls_back_to_legacy_manual_capture_only_on_explicit_rejection() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "BAD_REQUEST_ERROR",
                        "description": "capture is/are not required and should not be sent",
                        "reason": "extra_field_sent",
                        "metadata": {"must_not_cross_boundary": "provider-detail"},
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "order_legacy",
                "entity": "order",
                "amount": 1_000,
                "currency": "INR",
                "receipt": "chkr-legacy",
                "status": "created",
                "created_at": 1_787_571_200,
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.razorpay.com",
    )
    gateway = RazorpayTestModePaymentGateway(_settings(), client=client)

    order = await gateway.create_manual_capture_order(
        amount=Money(amount_subunits=1_000, currency="INR"),
        receipt="chkr-legacy",
    )
    await client.aclose()

    assert order.order_id == "order_legacy"
    assert len(requests) == 2
    assert json.loads(requests[0].content)["capture"] == "manual"
    assert "payment_capture" not in json.loads(requests[0].content)
    assert json.loads(requests[1].content)["payment_capture"] is False
    assert "capture" not in json.loads(requests[1].content)


async def test_adapter_does_not_fallback_for_an_unrecognized_provider_rejection() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "BAD_REQUEST_ERROR",
                    "description": "another field failed validation",
                    "reason": "input_validation_failed",
                }
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.razorpay.com",
    )
    gateway = RazorpayTestModePaymentGateway(_settings(), client=client)

    with pytest.raises(RazorpayActionError) as captured:
        await gateway.create_manual_capture_order(
            amount=Money(amount_subunits=1_000, currency="INR"),
            receipt="chkr-rejected",
        )
    await client.aclose()

    assert captured.value.code is ActionControlErrorCode.PROVIDER_REJECTED
    assert len(requests) == 1


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
