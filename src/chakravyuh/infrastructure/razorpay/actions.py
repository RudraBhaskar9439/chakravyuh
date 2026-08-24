"""Bounded Razorpay Payments adapter hard-wired to Test Mode credentials."""

from __future__ import annotations

import re
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chakravyuh.config import Settings
from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.enums import PaymentStatus
from chakravyuh.domain.errors import (
    ActionControlErrorCode,
    RazorpayActionError,
)
from chakravyuh.domain.money import Money

_API_BASE_URL = "https://api.razorpay.com"
_PAYMENT_ID = re.compile(r"^pay_[A-Za-z0-9]+$")
_MAX_RESPONSE_BYTES = 65_536


class DisabledRazorpayPaymentGateway:
    """Fail-closed adapter used while the Test Mode action kill switch is off."""

    async def fetch_payment(self, payment_id: str) -> ProviderPaymentState:
        del payment_id
        raise RazorpayActionError(
            ActionControlErrorCode.PROVIDER_UNAVAILABLE,
            retryable=False,
        )

    async def capture_payment(self, payment_id: str, amount: Money) -> ProviderPaymentState:
        del payment_id, amount
        raise RazorpayActionError(
            ActionControlErrorCode.PROVIDER_UNAVAILABLE,
            retryable=False,
        )

    async def close(self) -> None:
        return None


class _PaymentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^pay_[A-Za-z0-9]+$", max_length=255)
    entity: str
    amount: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: PaymentStatus
    captured: bool
    order_id: str | None = Field(default=None, max_length=255)


class RazorpayTestModePaymentGateway:
    """Fetch and capture payments without ever accepting a live credential."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not settings.razorpay_test_actions_configured:
            raise ValueError("Razorpay Test Mode actions are not configured")
        assert settings.razorpay_key_id is not None
        assert settings.razorpay_key_secret is not None
        self._auth = httpx.BasicAuth(
            settings.razorpay_key_id,
            settings.razorpay_key_secret.get_secret_value(),
        )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=_API_BASE_URL,
            follow_redirects=False,
            timeout=httpx.Timeout(settings.razorpay_action_timeout_seconds),
            trust_env=False,
            headers={"Accept": "application/json", "User-Agent": "chakravyuh/0.9"},
        )

    async def fetch_payment(self, payment_id: str) -> ProviderPaymentState:
        _validate_payment_id(payment_id)
        response = await self._request("GET", f"/v1/payments/{payment_id}")
        return _provider_state(response, expected_payment_id=payment_id)

    async def capture_payment(self, payment_id: str, amount: Money) -> ProviderPaymentState:
        _validate_payment_id(payment_id)
        response = await self._request(
            "POST",
            f"/v1/payments/{payment_id}/capture",
            json={"amount": amount.amount_subunits, "currency": amount.currency},
        )
        state = _provider_state(response, expected_payment_id=payment_id)
        if (
            state.amount != amount
            or state.status is not PaymentStatus.CAPTURED
            or not state.captured
        ):
            raise RazorpayActionError(
                ActionControlErrorCode.PROVIDER_INVALID_RESPONSE,
                retryable=False,
            )
        return state

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **parameters: Any) -> Any:
        try:
            response = await self._client.request(
                method,
                path,
                auth=self._auth,
                **parameters,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as failure:
            raise RazorpayActionError(
                ActionControlErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
            ) from failure
        if response.status_code == 429 or response.status_code >= 500:
            raise RazorpayActionError(
                ActionControlErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
            )
        if response.status_code >= 400:
            raise RazorpayActionError(
                ActionControlErrorCode.PROVIDER_REJECTED,
                retryable=False,
            )
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise RazorpayActionError(
                ActionControlErrorCode.PROVIDER_INVALID_RESPONSE,
                retryable=False,
            )
        try:
            return response.json()
        except ValueError as failure:
            raise RazorpayActionError(
                ActionControlErrorCode.PROVIDER_INVALID_RESPONSE,
                retryable=False,
            ) from failure


def _validate_payment_id(payment_id: str) -> None:
    if len(payment_id) > 255 or _PAYMENT_ID.fullmatch(payment_id) is None:
        raise RazorpayActionError(
            ActionControlErrorCode.PROVIDER_INVALID_RESPONSE,
            retryable=False,
        )


def _provider_state(payload: Any, *, expected_payment_id: str) -> ProviderPaymentState:
    try:
        parsed = _PaymentResponse.model_validate(payload)
    except ValidationError as failure:
        raise RazorpayActionError(
            ActionControlErrorCode.PROVIDER_INVALID_RESPONSE,
            retryable=False,
        ) from failure
    if parsed.id != expected_payment_id or parsed.entity != "payment":
        raise RazorpayActionError(
            ActionControlErrorCode.PROVIDER_INVALID_RESPONSE,
            retryable=False,
        )
    return ProviderPaymentState(
        payment_id=parsed.id,
        status=parsed.status,
        amount=Money(amount_subunits=parsed.amount, currency=parsed.currency),
        captured=parsed.captured,
        order_id=parsed.order_id,
    )
