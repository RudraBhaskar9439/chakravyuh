"""Authenticated Prometheus scrape endpoint for bounded process metrics."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from chakravyuh.api.operator_auth import OperatorPrincipal, require_operator, require_scope
from chakravyuh.domain.enums import OperatorScope

router = APIRouter(tags=["operations"])
OperatorDependency = Annotated[OperatorPrincipal, Depends(require_operator)]


@router.get("/internal/metrics", include_in_schema=False)
async def metrics(request: Request, principal: OperatorDependency) -> Response:
    require_scope(principal, OperatorScope.METRICS_READ)
    body: str = await request.app.state.process_metrics.render_prometheus()
    return Response(
        body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )
