"""Scoped API for creating and verifying one fixed-value Razorpay Test Checkout."""

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from chakravyuh.api.operator_auth import OperatorPrincipal, require_operator, require_scope
from chakravyuh.application.ports import TestCheckoutControlPlane
from chakravyuh.domain.enums import OperatorScope
from chakravyuh.domain.errors import (
    ActionControlErrorCode,
    RazorpayActionError,
    TestCheckoutError,
    TestCheckoutErrorCode,
)
from chakravyuh.domain.test_checkout import PreparedTestCheckout, TestCheckoutVerification

router = APIRouter(prefix="/v1/demo/checkout", tags=["test-checkout"])
OperatorDependency = Annotated[OperatorPrincipal, Depends(require_operator)]


class CheckoutVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    razorpay_order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=255)
    razorpay_payment_id: str = Field(pattern=r"^pay_[A-Za-z0-9]+$", max_length=255)
    razorpay_signature: str = Field(pattern=r"^[0-9A-Fa-f]{64}$")


class PublicCheckoutOrder(BaseModel):
    """Only fields required by the hosted Checkout cross the browser boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checkout_id: UUID
    order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=255)
    amount_subunits: int = Field(gt=0)
    currency: Literal["INR"]
    expires_at: AwareDatetime


class PreparedCheckoutResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order: PublicCheckoutOrder
    public_key_id: str = Field(pattern=r"^rzp_test_[A-Za-z0-9]+$", max_length=255)
    display_name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=255)


class CheckoutPaymentProof(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    payment_id: str = Field(pattern=r"^pay_[A-Za-z0-9]+$", max_length=255)
    order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=255)
    status: Literal["authorized"]
    amount_subunits: int = Field(gt=0)
    currency: Literal["INR"]
    captured: Literal[False]


class CheckoutVerificationResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verification_id: UUID
    verification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    verified_at: AwareDatetime
    payment: CheckoutPaymentProof


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def prepare_test_checkout(
    request: Request,
    response: Response,
    principal: OperatorDependency,
) -> PreparedCheckoutResponse:
    require_scope(principal, OperatorScope.TEST_CHECKOUT)
    response.headers["Cache-Control"] = "no-store"
    try:
        prepared = await _control_plane(request).prepare(
            principal_id=principal.principal_id,
            request_id=request.state.request_id,
        )
        return _public_prepared(prepared)
    except (TestCheckoutError, RazorpayActionError) as failure:
        raise _http_error(failure) from failure


@router.post("/verifications")
async def verify_test_checkout(
    body: CheckoutVerificationRequest,
    request: Request,
    response: Response,
    principal: OperatorDependency,
) -> CheckoutVerificationResponse:
    require_scope(principal, OperatorScope.TEST_CHECKOUT)
    response.headers["Cache-Control"] = "no-store"
    try:
        verification = await _control_plane(request).verify(
            order_id=body.razorpay_order_id,
            payment_id=body.razorpay_payment_id,
            signature=body.razorpay_signature,
            principal_id=principal.principal_id,
            request_id=request.state.request_id,
        )
        return _public_verification(verification)
    except (TestCheckoutError, RazorpayActionError) as failure:
        raise _http_error(failure) from failure


def _control_plane(request: Request) -> TestCheckoutControlPlane:
    return cast("TestCheckoutControlPlane", request.app.state.test_checkout_control_plane)


def _public_prepared(prepared: PreparedTestCheckout) -> PreparedCheckoutResponse:
    provider = prepared.order.provider_order
    return PreparedCheckoutResponse(
        order=PublicCheckoutOrder(
            checkout_id=prepared.order.checkout_id,
            order_id=provider.order_id,
            amount_subunits=provider.amount.amount_subunits,
            currency=provider.amount.currency,
            expires_at=prepared.order.expires_at,
        ),
        public_key_id=prepared.public_key_id,
        display_name=prepared.display_name,
        description=prepared.description,
    )


def _public_verification(
    verification: TestCheckoutVerification,
) -> CheckoutVerificationResponse:
    payment = verification.payment
    assert payment.order_id is not None
    return CheckoutVerificationResponse(
        verification_id=verification.verification_id,
        verification_hash=verification.verification_hash,
        verified_at=verification.verified_at,
        payment=CheckoutPaymentProof(
            payment_id=payment.payment_id,
            order_id=payment.order_id,
            status=payment.status.value,
            amount_subunits=payment.amount.amount_subunits,
            currency=payment.amount.currency,
            captured=payment.captured,
        ),
    )


def _http_error(failure: TestCheckoutError | RazorpayActionError) -> HTTPException:
    if isinstance(failure, RazorpayActionError):
        provider_mapping = {
            ActionControlErrorCode.PROVIDER_UNAVAILABLE: (
                status.HTTP_503_SERVICE_UNAVAILABLE,
                TestCheckoutErrorCode.PROVIDER_UNAVAILABLE,
            ),
            ActionControlErrorCode.PROVIDER_REJECTED: (
                status.HTTP_502_BAD_GATEWAY,
                TestCheckoutErrorCode.PROVIDER_REJECTED,
            ),
            ActionControlErrorCode.PROVIDER_INVALID_RESPONSE: (
                status.HTTP_502_BAD_GATEWAY,
                TestCheckoutErrorCode.PROVIDER_INVALID_RESPONSE,
            ),
        }
        status_code, code = provider_mapping.get(
            failure.code,
            (status.HTTP_502_BAD_GATEWAY, TestCheckoutErrorCode.PROVIDER_INVALID_RESPONSE),
        )
    else:
        code = failure.code
        if code is TestCheckoutErrorCode.DISABLED:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif code is TestCheckoutErrorCode.ORDER_NOT_FOUND:
            status_code = status.HTTP_404_NOT_FOUND
        elif code is TestCheckoutErrorCode.INVALID_SIGNATURE:
            status_code = status.HTTP_400_BAD_REQUEST
        elif code is TestCheckoutErrorCode.PROVIDER_UNAVAILABLE:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif code in {
            TestCheckoutErrorCode.PROVIDER_REJECTED,
            TestCheckoutErrorCode.PROVIDER_INVALID_RESPONSE,
        }:
            status_code = status.HTTP_502_BAD_GATEWAY
        else:
            status_code = status.HTTP_409_CONFLICT
    return HTTPException(status_code=status_code, detail={"code": code.value})
