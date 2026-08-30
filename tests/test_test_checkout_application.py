"""Bounded Test Checkout application behavior."""

import hmac
from datetime import UTC, datetime, timedelta

import pytest

from chakravyuh.application.test_checkout import RazorpayTestCheckoutControlPlane
from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.enums import EventSource, PaymentStatus
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
from chakravyuh.domain.webhooks import RawWebhookEvent


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

    async def get_verification(self, payment_id: str) -> CheckoutVerification | None:
        return self.verifications.get(payment_id)


class MemoryProviderEventStore:
    def __init__(self) -> None:
        self.events: dict[tuple[str, EventSource, str], RawWebhookEvent] = {}

    async def append(self, event: RawWebhookEvent) -> bool:
        key = (event.merchant_id, event.source, event.source_event_id)
        existing = self.events.get(key)
        if existing is not None:
            assert existing == event
            return False
        self.events[key] = event
        return True

    async def get(
        self,
        merchant_id: str,
        source_event_id: str,
    ) -> RawWebhookEvent | None:
        return next(
            (
                event
                for key, event in self.events.items()
                if key[0] == merchant_id and key[2] == source_event_id
            ),
            None,
        )


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
    event_store: MemoryProviderEventStore | None = None,
) -> RazorpayTestCheckoutControlPlane:
    return RazorpayTestCheckoutControlPlane(
        repository,
        gateway,
        event_store=event_store,
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


async def test_verification_records_idempotent_authoritative_api_fallback() -> None:
    repository = MemoryCheckoutRepository()
    gateway = FakeGateway()
    event_store = MemoryProviderEventStore()
    service = _service(repository, gateway, event_store=event_store)
    await service.prepare(principal_id="maker", request_id="prepare-request")

    first = await service.verify(
        order_id="order_123",
        payment_id="pay_123",
        signature=_signature(gateway),
        principal_id="maker",
        request_id="verify-request",
    )
    second = await service.reconcile(
        payment_id="pay_123",
        principal_id="maker",
        request_id="reconcile-request",
    )

    assert second == first
    assert len(event_store.events) == 1
    event = next(iter(event_store.events.values()))
    assert event.source is EventSource.RAZORPAY_API
    assert event.event_type == "payment.authorized"
    assert event.source_event_id.startswith("checkout-evidence:")
    assert event.payload["payload"] == {
        "payment": {
            "entity": {
                "id": "pay_123",
                "entity": "payment",
                "amount": 1_000,
                "currency": "INR",
                "status": "authorized",
                "order_id": "order_123",
                "captured": False,
            }
        }
    }


async def test_failed_checkout_is_reverified_and_ingested_without_trusting_browser_error() -> None:
    repository = MemoryCheckoutRepository()
    gateway = FakeGateway()
    event_store = MemoryProviderEventStore()
    service = _service(repository, gateway, event_store=event_store)
    await service.prepare(principal_id="maker", request_id="prepare-request")
    gateway.payment = gateway.payment.model_copy(update={"status": PaymentStatus.FAILED})

    evidence = await service.verify_failure(
        order_id="order_123",
        payment_id="pay_123",
        principal_id="maker",
        request_id="failure-request",
    )

    assert evidence.payment.status is PaymentStatus.FAILED
    assert evidence.evidence_hash != "0" * 64
    event = next(iter(event_store.events.values()))
    assert event.source is EventSource.RAZORPAY_API
    assert event.event_type == "payment.failed"
    payload = event.payload["payload"]
    assert isinstance(payload, dict)
    payment = payload["payment"]
    assert isinstance(payment, dict)
    entity = payment["entity"]
    assert isinstance(entity, dict)
    assert entity["status"] == "failed"


async def test_provider_proof_binds_live_state_to_original_checkout_verification() -> None:
    repository = MemoryCheckoutRepository()
    gateway = FakeGateway()
    service = _service(repository, gateway)
    await service.prepare(principal_id="maker", request_id="prepare-request")
    verification = await service.verify(
        order_id="order_123",
        payment_id="pay_123",
        signature=_signature(gateway),
        principal_id="maker",
        request_id="verify-request",
    )
    gateway.payment = gateway.payment.model_copy(
        update={"status": PaymentStatus.CAPTURED, "captured": True}
    )

    proof = await service.proof(
        payment_id="pay_123",
        principal_id="judge-reader",
        request_id="proof-request",
    )

    assert proof.verification == verification
    assert proof.provider_state.status is PaymentStatus.CAPTURED
    assert proof.provider_state.captured is True
    assert proof.proof_hash != "0" * 64


async def test_reconciliation_requires_prior_verification() -> None:
    service = _service(MemoryCheckoutRepository(), FakeGateway())

    with pytest.raises(CheckoutError) as missing:
        await service.reconcile(
            payment_id="pay_123",
            principal_id="maker",
            request_id="request",
        )

    assert missing.value.code is CheckoutErrorCode.VERIFICATION_NOT_FOUND


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
