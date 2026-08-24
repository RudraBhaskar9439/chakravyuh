"""Authenticated operator endpoints for the deterministic recovery action lifecycle."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from chakravyuh.api.operator_auth import OperatorPrincipal, require_operator
from chakravyuh.application.ports import ActionControlPlane
from chakravyuh.domain.actions import ActionView
from chakravyuh.domain.enums import ActionApprovalDecision
from chakravyuh.domain.errors import ActionControlError, ActionControlErrorCode

router = APIRouter(prefix="/v1/operator", tags=["operator-actions"])
OperatorDependency = Annotated[OperatorPrincipal, Depends(require_operator)]


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ActionApprovalDecision
    rationale: str = Field(min_length=1, max_length=500)


@router.get("/incidents/{incident_id}/actions")
async def list_actions(
    incident_id: UUID,
    request: Request,
    response: Response,
    principal: OperatorDependency,
) -> tuple[ActionView, ...]:
    response.headers["Cache-Control"] = "no-store"
    return tuple(
        await _control_plane(request).list_for_incident(
            incident_id,
            principal_id=principal.principal_id,
            request_id=request.state.request_id,
        )
    )


@router.post(
    "/incidents/{incident_id}/actions/proposals",
    status_code=status.HTTP_201_CREATED,
)
async def create_proposal(
    incident_id: UUID,
    request: Request,
    response: Response,
    principal: OperatorDependency,
) -> ActionView:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await _control_plane(request).propose(
            incident_id,
            principal_id=principal.principal_id,
            request_id=request.state.request_id,
        )
    except ActionControlError as failure:
        raise _http_error(failure) from failure


@router.post("/actions/{proposal_id}/decisions")
async def decide_proposal(
    proposal_id: UUID,
    body: ApprovalDecisionRequest,
    request: Request,
    response: Response,
    principal: OperatorDependency,
) -> ActionView:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await _control_plane(request).decide(
            proposal_id,
            principal_id=principal.principal_id,
            request_id=request.state.request_id,
            decision=body.decision,
            rationale=body.rationale,
        )
    except ActionControlError as failure:
        raise _http_error(failure) from failure


@router.post("/actions/{proposal_id}/execute")
async def execute_proposal(
    proposal_id: UUID,
    request: Request,
    response: Response,
    principal: OperatorDependency,
) -> ActionView:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await _control_plane(request).execute(
            proposal_id,
            principal_id=principal.principal_id,
            request_id=request.state.request_id,
        )
    except ActionControlError as failure:
        raise _http_error(failure) from failure


def _control_plane(request: Request) -> ActionControlPlane:
    return cast("ActionControlPlane", request.app.state.action_control_plane)


def _http_error(failure: ActionControlError) -> HTTPException:
    if failure.code is ActionControlErrorCode.NOT_FOUND:
        status_code = status.HTTP_404_NOT_FOUND
    elif failure.code is ActionControlErrorCode.POLICY_DENIED:
        status_code = status.HTTP_403_FORBIDDEN
    else:
        status_code = status.HTTP_409_CONFLICT
    return HTTPException(status_code=status_code, detail={"code": failure.code.value})
