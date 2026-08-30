"""Bounded Razorpay Test Checkout creation and proof verification."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from chakravyuh.application.ports import (
    RazorpayTestCheckoutGateway,
    TestCheckoutRepository,
    WebhookEventStore,
)
from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.enums import EventSource, PaymentStatus
from chakravyuh.domain.errors import TestCheckoutError, TestCheckoutErrorCode
from chakravyuh.domain.money import Money
from chakravyuh.domain.test_checkout import (
    PreparedTestCheckout,
    TestCheckoutFailureEvidence,
    TestCheckoutProviderProof,
    TestCheckoutVerification,
    create_test_checkout_failure_evidence,
    create_test_checkout_order,
    create_test_checkout_provider_proof,
    create_test_checkout_verification,
)
from chakravyuh.domain.webhooks import RawWebhookEvent


class RazorpayTestCheckoutControlPlane:
    """Create only fixed-value manual Test orders and verify exact Checkout proofs."""

    def __init__(
        self,
        repository: TestCheckoutRepository,
        gateway: RazorpayTestCheckoutGateway,
        *,
        event_store: WebhookEventStore | None = None,
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
        self._event_store = event_store
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
        recorded = await self._repository.record_verification(verification)
        await self._record_authoritative_authorization(order.merchant_id, recorded)
        return recorded

    async def reconcile(
        self,
        *,
        payment_id: str,
        principal_id: str,
        request_id: str,
    ) -> TestCheckoutVerification:
        """Re-ingest a previously verified payment when its webhook is delayed or absent.

        The operator identity and request ID are intentionally accepted for the control-plane
        contract and transport audit. The immutable verification remains the event provenance.
        """
        del principal_id, request_id
        self._require_enabled()
        verification = await self._repository.get_verification(payment_id)
        if verification is None:
            raise TestCheckoutError(TestCheckoutErrorCode.VERIFICATION_NOT_FOUND)
        order_id = verification.payment.order_id
        if order_id is None:  # pragma: no cover - domain contract guard
            raise TestCheckoutError(TestCheckoutErrorCode.PAYMENT_MISMATCH)
        order = await self._repository.get_order(order_id)
        if order is None:  # pragma: no cover - append-only ledger contract guard
            raise TestCheckoutError(TestCheckoutErrorCode.ORDER_NOT_FOUND)
        current = await self._gateway.fetch_payment(payment_id)
        if current.order_id != order_id or current.amount != verification.payment.amount:
            raise TestCheckoutError(TestCheckoutErrorCode.PAYMENT_MISMATCH)
        if current.status is not PaymentStatus.AUTHORIZED or current.captured:
            raise TestCheckoutError(TestCheckoutErrorCode.PAYMENT_NOT_AUTHORIZED)
        await self._record_authoritative_authorization(order.merchant_id, verification)
        return verification

    async def verify_failure(
        self,
        *,
        order_id: str,
        payment_id: str,
        principal_id: str,
        request_id: str,
    ) -> TestCheckoutFailureEvidence:
        """Verify a browser-observed failure against Razorpay before opening the journey."""
        self._require_enabled()
        order = await self._repository.get_order(order_id)
        if order is None:
            raise TestCheckoutError(TestCheckoutErrorCode.ORDER_NOT_FOUND)
        verified_at = datetime.now(UTC)
        if order.expires_at <= verified_at:
            raise TestCheckoutError(TestCheckoutErrorCode.ORDER_EXPIRED)
        payment = await self._gateway.fetch_payment(payment_id)
        if payment.order_id != order_id or payment.amount != order.provider_order.amount:
            raise TestCheckoutError(TestCheckoutErrorCode.PAYMENT_MISMATCH)
        if payment.status is not PaymentStatus.FAILED or payment.captured:
            raise TestCheckoutError(TestCheckoutErrorCode.PAYMENT_MISMATCH)
        evidence = create_test_checkout_failure_evidence(
            checkout_id=order.checkout_id,
            payment=payment,
            verified_by=principal_id,
            request_id=request_id,
            verified_at=verified_at,
        )
        await self._record_authoritative_payment(
            order.merchant_id,
            payment,
            event_type="payment.failed",
            recorded_at=verified_at,
            evidence_id=evidence.evidence_id,
        )
        return evidence

    async def proof(
        self,
        *,
        payment_id: str,
        principal_id: str,
        request_id: str,
    ) -> TestCheckoutProviderProof:
        """Re-query Razorpay without mutating it and bind the response to Checkout proof."""
        del principal_id, request_id
        self._require_enabled()
        verification = await self._repository.get_verification(payment_id)
        if verification is None:
            raise TestCheckoutError(TestCheckoutErrorCode.VERIFICATION_NOT_FOUND)
        current = await self._gateway.fetch_payment(payment_id)
        original = verification.payment
        if current.order_id != original.order_id or current.amount != original.amount:
            raise TestCheckoutError(TestCheckoutErrorCode.PAYMENT_MISMATCH)
        return create_test_checkout_provider_proof(
            verification=verification,
            provider_state=current,
            checked_at=datetime.now(UTC),
        )

    async def _record_authoritative_authorization(
        self,
        merchant_id: str,
        verification: TestCheckoutVerification,
    ) -> None:
        if self._event_store is None:
            return
        await self._record_authoritative_payment(
            merchant_id,
            verification.payment,
            event_type="payment.authorized",
            recorded_at=verification.verified_at,
            evidence_id=verification.verification_id,
        )

    async def _record_authoritative_payment(
        self,
        merchant_id: str,
        payment: ProviderPaymentState,
        *,
        event_type: str,
        recorded_at: datetime,
        evidence_id: UUID,
    ) -> None:
        if self._event_store is None:
            return
        assert payment.order_id is not None
        entity = {
            "id": payment.payment_id,
            "entity": "payment",
            "amount": payment.amount.amount_subunits,
            "currency": payment.amount.currency,
            "status": payment.status.value,
            "order_id": payment.order_id,
            "captured": payment.captured,
        }
        payload = {
            "entity": "event",
            "event": event_type,
            "created_at": int(recorded_at.timestamp()),
            "contains": ["payment"],
            "payload": {"payment": {"entity": entity}},
        }
        raw_body = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        event = RawWebhookEvent(
            event_id=uuid5(
                NAMESPACE_URL,
                f"chakravyuh:razorpay-api:{merchant_id}:{payment.payment_id}:{event_type}",
            ),
            merchant_id=merchant_id,
            source=EventSource.RAZORPAY_API,
            source_event_id=f"checkout-evidence:{evidence_id}:{event_type}",
            event_type=event_type,
            occurred_at=recorded_at,
            observed_at=recorded_at,
            payload=payload,
            raw_body=raw_body,
        )
        await self._event_store.append(event)

    def _require_enabled(self) -> None:
        if not self._enabled or self._merchant_id is None or self._public_key_id is None:
            raise TestCheckoutError(TestCheckoutErrorCode.DISABLED)
