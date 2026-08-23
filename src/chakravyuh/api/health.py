"""Liveness and readiness endpoints."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from chakravyuh import __version__

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Stable health-check contract for infrastructure and operators."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: str
    version: str
    environment: str
    timestamp: datetime
    checks: dict[str, Literal["ok"]]


def _response(request: Request, *, checks: dict[str, Literal["ok"]]) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
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
async def readiness(request: Request) -> HealthResponse:
    """Confirm Phase 1 configuration readiness.

    Dependency probes are registered alongside their adapters in Phase 3. Returning
    dependency health before those adapters exist would create a misleading signal.
    """
    return _response(request, checks={"configuration": "ok"})
