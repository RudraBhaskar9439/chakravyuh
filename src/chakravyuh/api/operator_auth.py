"""Constant-time bearer authentication for the internal operator API."""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_BEARER = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class OperatorPrincipal:
    principal_id: str


async def require_operator(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_BEARER)],
) -> OperatorPrincipal:
    configured = request.app.state.settings.operator_token_hashes
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator API is not configured",
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    presented_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    matched_principal: str | None = None
    for principal_id, expected_hash in configured.items():
        if secrets.compare_digest(presented_hash, expected_hash):
            matched_principal = principal_id
    if matched_principal is None:
        raise _unauthorized()
    return OperatorPrincipal(principal_id=matched_principal)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid operator credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
