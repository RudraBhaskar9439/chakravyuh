"""Bounded Razorpay Test Checkout creation and proof verification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from chakravyuh.application.ports import RazorpayTestCheckoutGateway, TestCheckoutRepository
from chakravyuh.domain.enums import PaymentStatus
from chakravyuh.domain.errors import TestCheckoutError, TestCheckoutErrorCode
from chakravyuh.domain.money import Money
from chakravyuh.domain.test_checkout import (
    PreparedTestCheckout,
    TestCheckoutVerification,
    create_test_checkout_order,
    create_test_checkout_verification,
)


class RazorpayTestCheckoutControlPlane:
    """Create only fixed-value manual Test orders and verify exact Checkout proofs."""

    def __init__(
        self,
        repository: TestCheckoutRepository,
        gateway: RazorpayTestCheckoutGateway,
        *,
        enabled: bool,
        merchant_id: str | None,
        public_key_id: str | None,
        amount_subunits: int,
        ttl_seconds: int,
        display_name: str = "Chakravyuh",
        description: str = "Evidence-first payment recovery demonstration",
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._enabled = enabled
        self._merchant_id = merchant_id
        self._public_key_id = public_key_id
        self._amount = Money(amount_subunits=amount_subunits, currency="INR")
        self._ttl_seconds = ttl_seconds
        self._display_name = display_name
        self._description = description

    async def prepare(self, *, principal_id: str, request_id: str) -> PreparedTestCheckout:
        self._require_enabled()
        assert self._merchant_id is not None
        assert self._public_key_id is not None
        created_at = datetime.now(UTC)
        checkout_id = uuid4()
        receipt = f"chkr-{checkout_id.hex[:32]}"
        provider_order = await self._gateway.create_manual_capture_order(
            amount=self._amount,
            receipt=receipt,
        )
        if provider_order.amount != self._amount or provider_order.receipt != receipt:
            raise TestCheckoutError(TestCheckoutErrorCode.PROVIDER_INVALID_RESPONSE)
        order = create_test_checkout_order(
            checkout_id=checkout_id,
            merchant_id=self._merchant_id,
            provider_order=provider_order,
            created_by=principal_id,
            request_id=request_id,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=self._ttl_seconds),
        )
        recorded = await self._repository.record_order(order)
        return PreparedTestCheckout(
            order=recorded,
            public_key_id=self._public_key_id,
            display_name=self._display_name,
            description=self._description,
        )

    async def verify(
        self,
        *,
        order_id: str,
        payment_id: str,
        signature: str,
        principal_id: str,
        request_id: str,
    ) -> TestCheckoutVerification:
        self._require_enabled()
        if not self._gateway.verify_checkout_signature(
            order_id=order_id,
            payment_id=payment_id,
            signature=signature,
        ):
            raise TestCheckoutError(TestCheckoutErrorCode.INVALID_SIGNATURE)
        order = await self._repository.get_order(order_id)
        if order is None:
            raise TestCheckoutError(TestCheckoutErrorCode.ORDER_NOT_FOUND)
        verified_at = datetime.now(UTC)
        if order.expires_at <= verified_at:
            raise TestCheckoutError(TestCheckoutErrorCode.ORDER_EXPIRED)
        payment = await self._gateway.fetch_payment(payment_id)
        if payment.order_id != order_id or payment.amount != order.provider_order.amount:
            raise TestCheckoutError(TestCheckoutErrorCode.PAYMENT_MISMATCH)
        if payment.status is not PaymentStatus.AUTHORIZED or payment.captured:
            raise TestCheckoutError(TestCheckoutErrorCode.PAYMENT_NOT_AUTHORIZED)
        verification = create_test_checkout_verification(
            checkout_id=order.checkout_id,
            payment=payment,
            verified_by=principal_id,
            request_id=request_id,
            verified_at=verified_at,
        )
        return await self._repository.record_verification(verification)

    def _require_enabled(self) -> None:
        if not self._enabled or self._merchant_id is None or self._public_key_id is None:
            raise TestCheckoutError(TestCheckoutErrorCode.DISABLED)
