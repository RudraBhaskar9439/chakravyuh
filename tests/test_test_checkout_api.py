"""Authenticated API contract for the fixed-value Razorpay Test Checkout."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import ASGITransport, AsyncClient

from chakravyuh.api.main import create_app
from chakravyuh.config import Settings
from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.enums import OperatorScope, PaymentStatus
from chakravyuh.domain.errors import TestCheckoutError as CheckoutError
from chakravyuh.domain.errors import TestCheckoutErrorCode as CheckoutErrorCode
from chakravyuh.domain.money import Money
from chakravyuh.domain.test_checkout import (
    PreparedTestCheckout,
    ProviderManualCaptureOrder,
    create_test_checkout_order,
    create_test_checkout_verification,
)
from chakravyuh.domain.test_checkout import (
    TestCheckoutVerification as CheckoutVerification,
)

TOKEN = "test-checkout-operator-token-with-enough-entropy"


def _prepared() -> PreparedTestCheckout:
    now = datetime.now(UTC)
    order = create_test_checkout_order(
        merchant_id="merchant-test",
        provider_order=ProviderManualCaptureOrder(
            order_id="order_123",
            amount=Money(amount_subunits=1_000, currency="INR"),
            receipt="chkr-contract",
            provider_created_at=now,
        ),
        created_by="maker",
        request_id="prepare-request",
        created_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    return PreparedTestCheckout(
        order=order,
        public_key_id="rzp_test_contract",
        display_name="Chakravyuh",
        description="Test payment",
    )


class FakeControlPlane:
    def __init__(self) -> None:
        self.prepared = _prepared()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.failure: CheckoutError | None = None

    async def prepare(self, **parameters: Any) -> PreparedTestCheckout:
        self.calls.append(("prepare", parameters))
        if self.failure is not None:
            raise self.failure
        return self.prepared

    async def verify(self, **parameters: Any) -> CheckoutVerification:
        self.calls.append(("verify", parameters))
        if self.failure is not None:
            raise self.failure
        return create_test_checkout_verification(
            checkout_id=self.prepared.order.checkout_id,
            payment=ProviderPaymentState(
                payment_id="pay_123",
                status=PaymentStatus.AUTHORIZED,
                amount=Money(amount_subunits=1_000, currency="INR"),
                captured=False,
                order_id="order_123",
            ),
            verified_by=parameters["principal_id"],
            request_id=parameters["request_id"],
            verified_at=datetime.now(UTC),
        )

    async def reconcile(self, **parameters: Any) -> CheckoutVerification:
        self.calls.append(("reconcile", parameters))
        if self.failure is not None:
            raise self.failure
        return await self.verify(
            principal_id=parameters["principal_id"],
            request_id=parameters["request_id"],
        )

    async def proof(self, **parameters: Any) -> Any:
        from chakravyuh.domain.test_checkout import create_test_checkout_provider_proof

        self.calls.append(("proof", parameters))
        verification = await self.verify(
            principal_id=parameters["principal_id"],
            request_id=parameters["request_id"],
        )
        return create_test_checkout_provider_proof(
            verification=verification,
            provider_state=verification.payment.model_copy(
                update={"status": PaymentStatus.CAPTURED, "captured": True}
            ),
            checked_at=datetime.now(UTC),
        )


def _settings(*, allowed: bool = True) -> Settings:
    return Settings(
        environment="test",
        operator_token_hashes={"maker": hashlib.sha256(TOKEN.encode()).hexdigest()},
        operator_principal_scopes=(
            {"maker": [OperatorScope.TEST_CHECKOUT]}
            if allowed
            else {"maker": [OperatorScope.INCIDENT_READ]}
        ),
    )


def _client(control: FakeControlPlane, *, allowed: bool = True) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(
            app=create_app(
                _settings(allowed=allowed),
                test_checkout_control_plane=control,
            )
        ),
        base_url="http://test",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


async def test_prepare_and_verify_forward_scoped_operator_identity() -> None:
    control = FakeControlPlane()
    async with _client(control) as client:
        prepared = await client.post(
            "/v1/demo/checkout/orders",
            headers={"X-Request-ID": "prepare-api-request"},
        )
        verified = await client.post(
            "/v1/demo/checkout/verifications",
            headers={"X-Request-ID": "verify-api-request"},
            json={
                "razorpay_order_id": "order_123",
                "razorpay_payment_id": "pay_123",
                "razorpay_signature": "a" * 64,
            },
        )

    assert prepared.status_code == 201
    assert verified.status_code == 200
    assert prepared.headers["Cache-Control"] == verified.headers["Cache-Control"] == "no-store"
    assert prepared.json()["public_key_id"] == "rzp_test_contract"
    assert prepared.json()["order"]["order_id"] == "order_123"
    assert "merchant_id" not in prepared.json()["order"]
    assert "created_by" not in prepared.json()["order"]
    assert verified.json()["payment"]["status"] == "authorized"
    assert "verified_by" not in verified.json()
    assert "request_id" not in verified.json()
    assert control.calls[0] == (
        "prepare",
        {"principal_id": "maker", "request_id": "prepare-api-request"},
    )
    assert control.calls[1][1]["signature"] == "a" * 64
    assert control.calls[1][1]["request_id"] == "verify-api-request"


async def test_reconcile_forwards_scoped_operator_identity() -> None:
    control = FakeControlPlane()
    async with _client(control) as client:
        response = await client.post(
            "/v1/demo/checkout/verifications/pay_123/reconcile",
            headers={"X-Request-ID": "reconcile-api-request"},
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["payment"]["payment_id"] == "pay_123"
    assert control.calls[0] == (
        "reconcile",
        {
            "payment_id": "pay_123",
            "principal_id": "maker",
            "request_id": "reconcile-api-request",
        },
    )


async def test_provider_proof_requeries_razorpay_without_exposing_secrets() -> None:
    control = FakeControlPlane()
    async with _client(control) as client:
        response = await client.get(
            "/v1/demo/checkout/verifications/pay_123/proof",
            headers={"X-Request-ID": "proof-api-request"},
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["mode"] == "razorpay_test"
    assert body["original_authorization"]["status"] == "authorized"
    assert body["current_provider_state"]["status"] == "captured"
    assert body["current_provider_state"]["captured"] is True
    assert len(body["provider_proof_hash"]) == 64
    assert "signature" not in response.text
    assert control.calls[0] == (
        "proof",
        {
            "payment_id": "pay_123",
            "principal_id": "maker",
            "request_id": "proof-api-request",
        },
    )


async def test_checkout_api_rejects_missing_scope_and_invalid_body() -> None:
    control = FakeControlPlane()
    async with _client(control, allowed=False) as client:
        denied = await client.post("/v1/demo/checkout/orders")
    async with _client(control) as client:
        invalid = await client.post(
            "/v1/demo/checkout/verifications",
            json={
                "razorpay_order_id": "unsafe/order",
                "razorpay_payment_id": "pay_123",
                "razorpay_signature": "a" * 64,
            },
        )

    assert denied.status_code == 403
    assert invalid.status_code == 422
    assert control.calls == []


async def test_checkout_errors_are_stable_and_secret_free() -> None:
    expected = [
        (CheckoutErrorCode.DISABLED, 503),
        (CheckoutErrorCode.ORDER_NOT_FOUND, 404),
        (CheckoutErrorCode.INVALID_SIGNATURE, 400),
        (CheckoutErrorCode.PAYMENT_NOT_AUTHORIZED, 409),
    ]
    for code, status_code in expected:
        control = FakeControlPlane()
        control.failure = CheckoutError(code)
        async with _client(control) as client:
            response = await client.post("/v1/demo/checkout/orders")
        assert response.status_code == status_code
        assert response.json() == {"detail": {"code": code.value}}
