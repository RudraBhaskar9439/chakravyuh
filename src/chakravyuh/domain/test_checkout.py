"""Immutable Test Mode Checkout orders and verified payment proofs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.money import Money


class ProviderManualCaptureOrder(BaseModel):
    """Allowlisted Razorpay order response; no raw provider body crosses this boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=255)
    amount: Money
    receipt: str = Field(min_length=1, max_length=40)
    provider_created_at: AwareDatetime


class TestCheckoutOrder(BaseModel):
    """Append-only record of one bounded manual-capture Test Mode order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checkout_id: UUID = Field(default_factory=uuid4)
    merchant_id: str = Field(min_length=1, max_length=255)
    provider_order: ProviderManualCaptureOrder
    created_by: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=255)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: AwareDatetime
    order_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def expiry_and_hash_are_valid(self) -> TestCheckoutOrder:
        if self.expires_at <= self.created_at:
            msg = "test checkout order expiry must follow creation"
            raise ValueError(msg)
        if _order_hash(self) != self.order_hash:
            msg = "test checkout order hash does not match its canonical content"
            raise ValueError(msg)
        return self


class TestCheckoutVerification(BaseModel):
    """Append-only proof that Checkout returned an exact authorized Test Mode payment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verification_id: UUID = Field(default_factory=uuid4)
    checkout_id: UUID
    payment: ProviderPaymentState
    verified_by: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=255)
    verified_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    verification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def hash_is_valid(self) -> TestCheckoutVerification:
        if _verification_hash(self) != self.verification_hash:
            msg = "test checkout verification hash does not match its canonical content"
            raise ValueError(msg)
        return self


class TestCheckoutFailureEvidence(BaseModel):
    """Tamper-evident proof that a recorded Test Checkout order produced a failed payment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: UUID = Field(default_factory=uuid4)
    checkout_id: UUID
    payment: ProviderPaymentState
    verified_by: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=255)
    verified_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def failure_and_hash_are_valid(self) -> TestCheckoutFailureEvidence:
        if self.payment.status.value != "failed" or self.payment.captured:
            msg = "failure evidence requires an uncaptured failed payment"
            raise ValueError(msg)
        if _failure_evidence_hash(self) != self.evidence_hash:
            msg = "test checkout failure evidence hash does not match its canonical content"
            raise ValueError(msg)
        return self


class TestCheckoutProviderProof(BaseModel):
    """Tamper-evident, read-only re-verification of a Checkout payment at Razorpay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verification: TestCheckoutVerification
    provider_state: ProviderPaymentState
    checked_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def identity_amount_and_hash_are_valid(self) -> TestCheckoutProviderProof:
        original = self.verification.payment
        current = self.provider_state
        if (
            current.payment_id != original.payment_id
            or current.order_id != original.order_id
            or current.amount != original.amount
        ):
            msg = "provider proof does not match the verified Checkout identity and amount"
            raise ValueError(msg)
        if _provider_proof_hash(self) != self.proof_hash:
            msg = "provider proof hash does not match its canonical content"
            raise ValueError(msg)
        return self


class PreparedTestCheckout(BaseModel):
    """Browser-safe order parameters; the public key is intentionally not secret."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order: TestCheckoutOrder
    public_key_id: str = Field(pattern=r"^rzp_test_[A-Za-z0-9]+$", max_length=255)
    display_name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=255)


def create_test_checkout_order(
    *,
    merchant_id: str,
    provider_order: ProviderManualCaptureOrder,
    created_by: str,
    request_id: str,
    created_at: datetime,
    expires_at: datetime,
    checkout_id: UUID | None = None,
) -> TestCheckoutOrder:
    draft = TestCheckoutOrder.model_construct(
        checkout_id=checkout_id or uuid4(),
        merchant_id=merchant_id,
        provider_order=provider_order,
        created_by=created_by,
        request_id=request_id,
        created_at=created_at,
        expires_at=expires_at,
        order_hash="0" * 64,
    )
    return TestCheckoutOrder.model_validate(
        {**draft.model_dump(), "order_hash": _order_hash(draft)}
    )


def create_test_checkout_verification(
    *,
    checkout_id: UUID,
    payment: ProviderPaymentState,
    verified_by: str,
    request_id: str,
    verified_at: datetime,
    verification_id: UUID | None = None,
) -> TestCheckoutVerification:
    draft = TestCheckoutVerification.model_construct(
        verification_id=verification_id or uuid4(),
        checkout_id=checkout_id,
        payment=payment,
        verified_by=verified_by,
        request_id=request_id,
        verified_at=verified_at,
        verification_hash="0" * 64,
    )
    return TestCheckoutVerification.model_validate(
        {**draft.model_dump(), "verification_hash": _verification_hash(draft)}
    )


def create_test_checkout_provider_proof(
    *,
    verification: TestCheckoutVerification,
    provider_state: ProviderPaymentState,
    checked_at: datetime,
) -> TestCheckoutProviderProof:
    draft = TestCheckoutProviderProof.model_construct(
        verification=verification,
        provider_state=provider_state,
        checked_at=checked_at,
        proof_hash="0" * 64,
    )
    return TestCheckoutProviderProof.model_validate(
        {**draft.model_dump(), "proof_hash": _provider_proof_hash(draft)}
    )


def create_test_checkout_failure_evidence(
    *,
    checkout_id: UUID,
    payment: ProviderPaymentState,
    verified_by: str,
    request_id: str,
    verified_at: datetime,
    evidence_id: UUID | None = None,
) -> TestCheckoutFailureEvidence:
    draft = TestCheckoutFailureEvidence.model_construct(
        evidence_id=evidence_id or uuid4(),
        checkout_id=checkout_id,
        payment=payment,
        verified_by=verified_by,
        request_id=request_id,
        verified_at=verified_at,
        evidence_hash="0" * 64,
    )
    return TestCheckoutFailureEvidence.model_validate(
        {**draft.model_dump(), "evidence_hash": _failure_evidence_hash(draft)}
    )


def _order_hash(order: TestCheckoutOrder) -> str:
    return _hash(order.model_dump(mode="json", exclude={"order_hash"}))


def _verification_hash(verification: TestCheckoutVerification) -> str:
    return _hash(verification.model_dump(mode="json", exclude={"verification_hash"}))


def _provider_proof_hash(proof: TestCheckoutProviderProof) -> str:
    return _hash(proof.model_dump(mode="json", exclude={"proof_hash"}))


def _failure_evidence_hash(evidence: TestCheckoutFailureEvidence) -> str:
    return _hash(evidence.model_dump(mode="json", exclude={"evidence_hash"}))


def _hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()
