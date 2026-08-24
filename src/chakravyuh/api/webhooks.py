"""Authenticated provider webhook transport."""

from datetime import UTC, datetime
from re import compile as compile_pattern
from typing import Annotated

import structlog
from fastapi import APIRouter, Header, HTTPException, Path, Request, Response, status
from pydantic import BaseModel, ConfigDict

from chakravyuh.domain.errors import EventIdentityConflictError
from chakravyuh.infrastructure.razorpay.webhooks import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    decode_webhook,
    verify_webhook_signature,
)

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])
logger = structlog.get_logger(__name__)
_PROVIDER_EVENT_ID = compile_pattern(r"^[A-Za-z0-9_-]{1,255}$")


class WebhookAcceptedResponse(BaseModel):
    """Idempotent acknowledgement returned only after durable commit."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    accepted: bool


async def _read_bounded_body(request: Request, limit: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from error
        if declared_length < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        if declared_length > limit:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    if not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    return bytes(body)


@router.post(
    "/razorpay/{merchant_id}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_razorpay_webhook(
    merchant_id: Annotated[str, Path(min_length=1, max_length=255)],
    request: Request,
    response: Response,
    signature: Annotated[str | None, Header(alias="X-Razorpay-Signature")] = None,
    source_event_id: Annotated[str | None, Header(alias="X-Razorpay-Event-Id")] = None,
) -> WebhookAcceptedResponse:
    """Authenticate exact bytes, commit once, then acknowledge Razorpay."""
    settings = request.app.state.settings
    if settings.razorpay_merchant_id is None or not settings.webhook_secrets:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if merchant_id != settings.razorpay_merchant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if source_event_id is None or _PROVIDER_EVENT_ID.fullmatch(source_event_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    raw_body = await _read_bounded_body(request, settings.max_webhook_body_bytes)
    try:
        verify_webhook_signature(raw_body, signature, settings.webhook_secrets)
        event = decode_webhook(
            merchant_id=merchant_id,
            source_event_id=source_event_id,
            raw_body=raw_body,
            observed_at=datetime.now(UTC),
        )
    except InvalidWebhookSignatureError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from error
    except InvalidWebhookPayloadError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from error

    if (
        settings.razorpay_account_id is not None
        and event.account_id != settings.razorpay_account_id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    try:
        result = await request.app.state.ingest_webhook.execute(event)
    except EventIdentityConflictError as error:
        await logger.aerror(
            "webhook_identity_conflict",
            merchant_id=merchant_id,
            source_event_id=source_event_id,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from error

    if not result.accepted:
        response.status_code = status.HTTP_200_OK
    await logger.ainfo(
        "webhook_committed",
        merchant_id=merchant_id,
        source_event_id=source_event_id,
        event_type=event.event_type,
        accepted=result.accepted,
    )
    return WebhookAcceptedResponse(event_id=str(result.event_id), accepted=result.accepted)
