"""Bounded Test Checkout application behavior."""

import hmac
from datetime import UTC, datetime, timedelta

import pytest

from chakravyuh.application.test_checkout import RazorpayTestCheckoutControlPlane
from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.enums import PaymentStatus
from chakravyuh.domain.errors import (
    TestCheckoutError as CheckoutError,
)
from chakravyuh.domain.errors import (
    TestCheckoutErrorCode as CheckoutErrorCode,
)
from chakravyuh.domain.money import Money
from chakravyuh.domain.test_checkout import (
    ProviderManualCaptureOrder,
)
from chakravyuh.domain.test_checkout import (
    TestCheckoutOrder as CheckoutOrder,
)
from chakravyuh.domain.test_checkout import (
    TestCheckoutVerification as CheckoutVerification,
)


class MemoryCheckoutRepository:
    def __init__(self) -> None:
        self.orders: dict[str, CheckoutOrder] = {}
        self.verifications: dict[str, CheckoutVerification] = {}

    async def record_order(self, order: CheckoutOrder) -> CheckoutOrder:
        self.orders[order.provider_order.order_id] = order
        return order

    async def get_order(self, order_id: str) -> CheckoutOrder | None:
        return self.orders.get(order_id)

    async def record_verification(
        self,
        verification: CheckoutVerification,
    ) -> CheckoutVerification:
        payment_id = verification.payment.payment_id
        existing = self.verifications.get(payment_id)
        if existing is not None:
            return existing
        self.verifications[payment_id] = verification
        return verification


class FakeGateway:
    def __init__(self) -> None:
        self.secret = b"test-secret"
        self.created: list[tuple[Money, str]] = []
        self.payment = ProviderPaymentState(
            payment_id="pay_123",
            status=PaymentStatus.AUTHORIZED,
            amount=Money(amount_subunits=1_000, currency="INR"),
            captured=False,
            order_id="order_123",
        )

    async def create_manual_capture_order(
        self,
        *,
        amount: Money,
        receipt: str,
    ) -> ProviderManualCaptureOrder:
        self.created.append((amount, receipt))
        return ProviderManualCaptureOrder(
            order_id="order_123",
            amount=amount,
            receipt=receipt,
            provider_created_at=datetime.now(UTC),
        )

    def verify_checkout_signature(
        self,
        *,
        order_id: str,
        payment_id: str,
        signature: str,
    ) -> bool:
        expected = hmac.digest(self.secret, f"{order_id}|{payment_id}".encode(), "sha256").hex()
        return hmac.compare_digest(expected, signature)

    async def fetch_payment(self, payment_id: str) -> ProviderPaymentState:
        assert payment_id == self.payment.payment_id
        return self.payment

    async def capture_payment(self, payment_id: str, amount: Money) -> ProviderPaymentState:
        raise NotImplementedError

    async def close(self) -> None:
        return None


def _service(
    repository: MemoryCheckoutRepository,
    gateway: FakeGateway,
    *,
    enabled: bool = True,
) -> RazorpayTestCheckoutControlPlane:
    return RazorpayTestCheckoutControlPlane(
        repository,
        gateway,
        enabled=enabled,
        merchant_id="merchant-test",
        public_key_id="rzp_test_contract",
        amount_subunits=1_000,
        ttl_seconds=1_800,
    )


def _signature(gateway: FakeGateway) -> str:
    return hmac.digest(gateway.secret, b"order_123|pay_123", "sha256").hex()


async def test_prepares_fixed_manual_order_and_verifies_exact_authorization() -> None:
    repository = MemoryCheckoutRepository()
    gateway = FakeGateway()
    service = _service(repository, gateway)

    prepared = await service.prepare(principal_id="maker", request_id="prepare-request")
    verification = await service.verify(
        order_id="order_123",
        payment_id="pay_123",
        signature=_signature(gateway),
        principal_id="maker",
        request_id="verify-request",
    )

    assert prepared.public_key_id == "rzp_test_contract"
    assert prepared.order.provider_order.amount == Money(amount_subunits=1_000, currency="INR")
    assert prepared.order.order_hash != "0" * 64
    assert gateway.created[0][1].startswith("chkr-")
    assert verification.payment.status is PaymentStatus.AUTHORIZED
    assert verification.verification_hash != "0" * 64


async def test_checkout_is_fail_closed_and_rejects_invalid_signature() -> None:
    repository = MemoryCheckoutRepository()
    gateway = FakeGateway()
    disabled = _service(repository, gateway, enabled=False)
    with pytest.raises(CheckoutError) as disabled_failure:
        await disabled.prepare(principal_id="maker", request_id="request")
    assert disabled_failure.value.code is CheckoutErrorCode.DISABLED

    service = _service(repository, gateway)
    await service.prepare(principal_id="maker", request_id="request")
    with pytest.raises(CheckoutError) as signature_failure:
        await service.verify(
            order_id="order_123",
            payment_id="pay_123",
            signature="0" * 64,
            principal_id="maker",
            request_id="request",
        )
    assert signature_failure.value.code is CheckoutErrorCode.INVALID_SIGNATURE


async def test_verification_requires_a_known_unexpired_order() -> None:
    repository = MemoryCheckoutRepository()
    gateway = FakeGateway()
    service = _service(repository, gateway)
    with pytest.raises(CheckoutError) as missing:
        await service.verify(
            order_id="order_123",
            payment_id="pay_123",
            signature=_signature(gateway),
            principal_id="maker",
            request_id="request",
        )
    assert missing.value.code is CheckoutErrorCode.ORDER_NOT_FOUND

    prepared = await service.prepare(principal_id="maker", request_id="request")
    repository.orders["order_123"] = prepared.order.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    with pytest.raises(CheckoutError) as expired:
        await service.verify(
            order_id="order_123",
            payment_id="pay_123",
            signature=_signature(gateway),
            principal_id="maker",
            request_id="request",
        )
    assert expired.value.code is CheckoutErrorCode.ORDER_EXPIRED


@pytest.mark.parametrize(
    ("payment", "expected"),
    [
        (
            ProviderPaymentState(
                payment_id="pay_123",
                status=PaymentStatus.AUTHORIZED,
                amount=Money(amount_subunits=2_000, currency="INR"),
                captured=False,
                order_id="order_123",
            ),
            CheckoutErrorCode.PAYMENT_MISMATCH,
        ),
        (
            ProviderPaymentState(
                payment_id="pay_123",
                status=PaymentStatus.CAPTURED,
                amount=Money(amount_subunits=1_000, currency="INR"),
                captured=True,
                order_id="order_123",
            ),
            CheckoutErrorCode.PAYMENT_NOT_AUTHORIZED,
        ),
    ],
)
async def test_verification_rejects_changed_or_already_captured_payment(
    payment: ProviderPaymentState,
    expected: CheckoutErrorCode,
) -> None:
    repository = MemoryCheckoutRepository()
    gateway = FakeGateway()
    gateway.payment = payment
    service = _service(repository, gateway)
    await service.prepare(principal_id="maker", request_id="request")

    with pytest.raises(CheckoutError) as captured:
        await service.verify(
            order_id="order_123",
            payment_id="pay_123",
            signature=_signature(gateway),
            principal_id="maker",
            request_id="request",
        )
    assert captured.value.code is expected
