"""Authenticated, read-only incident and evidence endpoints for operators."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from starlette.responses import Response

from chakravyuh.api.operator_auth import OperatorPrincipal, require_operator, require_scope
from chakravyuh.application.ports import OperatorReadModel
from chakravyuh.domain.enums import IncidentStatus, OperatorScope
from chakravyuh.domain.operators import IncidentDetail, IncidentOverview, IncidentPage

router = APIRouter(
    prefix="/v1/operator",
    tags=["operator"],
)


OperatorDependency = Annotated[OperatorPrincipal, Depends(require_operator)]


@router.get("/overview")
async def overview(
    request: Request,
    response: Response,
    principal: OperatorDependency,
) -> IncidentOverview:
    require_scope(principal, OperatorScope.INCIDENT_READ)
    response.headers["Cache-Control"] = "no-store"
    return await _read_model(request).overview(
        principal_id=principal.principal_id,
        request_id=request.state.request_id,
    )


@router.get("/incidents")
async def list_incidents(
    request: Request,
    response: Response,
    principal: OperatorDependency,
    incident_statuses: Annotated[
        list[IncidentStatus] | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
) -> IncidentPage:
    require_scope(principal, OperatorScope.INCIDENT_READ)
    response.headers["Cache-Control"] = "no-store"
    try:
        return await _read_model(request).list_incidents(
            principal_id=principal.principal_id,
            request_id=request.state.request_id,
            statuses=tuple(item.value for item in incident_statuses or ()),
            limit=limit,
            cursor=cursor,
        )
    except ValueError as failure:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid incident query",
        ) from failure


@router.get("/incidents/{incident_id}")
async def get_incident(
    incident_id: UUID,
    request: Request,
    response: Response,
    principal: OperatorDependency,
) -> IncidentDetail:
    require_scope(principal, OperatorScope.INCIDENT_READ)
    response.headers["Cache-Control"] = "no-store"
    detail = await _read_model(request).get_incident(
        incident_id,
        principal_id=principal.principal_id,
        request_id=request.state.request_id,
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="incident not found",
        )
    return detail


def _read_model(request: Request) -> OperatorReadModel:
    return cast("OperatorReadModel", request.app.state.operator_read_model)
