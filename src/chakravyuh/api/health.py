"""Liveness and readiness endpoints."""

import asyncio
from datetime import UTC, datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError

from chakravyuh import __version__
from chakravyuh.domain.projections import GraphProjectionHealth

router = APIRouter(prefix="/health", tags=["health"])
logger = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    """Stable health-check contract for infrastructure and operators."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable"]
    service: str
    version: str
    environment: str
    timestamp: datetime
    checks: dict[str, Literal["ok", "error"]]


class DemoReadinessResponse(BaseModel):
    """Secret-free capability readiness for the public Test Mode judge flow."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable"]
    environment: str
    checks: dict[str, Literal["ok", "error"]]


def _response(
    request: Request,
    *,
    response_status: Literal["ok", "unavailable"] = "ok",
    checks: dict[str, Literal["ok", "error"]],
) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status=response_status,
        service="chakravyuh-api",
        version=__version__,
        environment=settings.environment,
        timestamp=datetime.now(UTC),
        checks=checks,
    )


@router.get("/live")
async def liveness(request: Request) -> HealthResponse:
    """Confirm that the process can serve HTTP."""
    return _response(request, checks={"process": "ok"})


@router.get("/ready")
async def readiness(request: Request, response: Response) -> HealthResponse:
    """Confirm that the authoritative PostgreSQL ledger is reachable."""
    try:
        await asyncio.wait_for(
            request.app.state.database.ping(),
            timeout=request.app.state.settings.postgres_readiness_timeout_seconds,
        )
    except (TimeoutError, OSError, RuntimeError, SQLAlchemyError):
        await logger.awarning("postgres_readiness_failed", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return _response(
            request,
            response_status="unavailable",
            checks={"configuration": "ok", "postgres": "error"},
        )
    return _response(request, checks={"configuration": "ok", "postgres": "ok"})


@router.get("/demo")
async def demo_readiness(request: Request, response: Response) -> DemoReadinessResponse:
    """Report judge-demo capabilities without exposing credentials or provider identifiers."""
    settings = request.app.state.settings
    diagnosis_configured = (
        settings.diagnosis_primary_provider == "openrouter"
        and settings.openrouter_api_key is not None
    ) or (settings.diagnosis_primary_provider == "gemini" and settings.gemini_api_key is not None)
    checks: dict[str, Literal["ok", "error"]] = {
        "test_checkout": "ok" if settings.test_checkout_enabled else "error",
        "test_mode_provider": ("ok" if settings.razorpay_test_credentials_configured else "error"),
        "bounded_actions": "ok" if settings.razorpay_test_actions_configured else "error",
        "diagnosis_provider": "ok" if diagnosis_configured else "error",
        "signed_webhook": "ok" if settings.webhook_secrets else "error",
    }
    available = all(value == "ok" for value in checks.values())
    if not available:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return DemoReadinessResponse(
        status="ok" if available else "unavailable",
        environment=settings.environment,
        checks=checks,
    )


@router.get("/graph")
async def graph_projection_health(request: Request, response: Response) -> GraphProjectionHealth:
    """Report graph reachability and PostgreSQL-authoritative projection lag."""

    result: GraphProjectionHealth = await request.app.state.check_graph_projection_health.execute()
    if not result.healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
