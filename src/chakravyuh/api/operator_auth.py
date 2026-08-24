"""Constant-time bearer authentication for the internal operator API."""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from chakravyuh.domain.enums import OperatorScope
from chakravyuh.infrastructure.rate_limiting import (
    RateLimitDecision,
    RateLimiter,
    RateLimiterUnavailableError,
)

_BEARER = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class OperatorPrincipal:
    principal_id: str
    scopes: frozenset[OperatorScope]


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
    await _enforce_limit(
        request,
        key=f"auth:{_client_identity(request)}",
        limit=request.app.state.settings.operator_auth_attempts_per_minute,
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
    await _enforce_limit(
        request,
        key=f"principal:{matched_principal}",
        limit=request.app.state.settings.operator_requests_per_minute,
    )
    return OperatorPrincipal(
        principal_id=matched_principal,
        scopes=request.app.state.settings.scopes_for_principal(matched_principal),
    )


def require_scope(principal: OperatorPrincipal, scope: OperatorScope) -> None:
    """Fail closed before a route can reach a privileged control-plane port."""

    if scope not in principal.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="operator permission denied",
        )


async def _enforce_limit(request: Request, *, key: str, limit: int) -> None:
    limiter: RateLimiter = request.app.state.operator_rate_limiter
    try:
        decision = await limiter.consume(key, limit=limit)
    except RateLimiterUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator authentication unavailable",
        ) from error
    if not decision.allowed:
        raise _rate_limited(decision)


def _client_identity(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _rate_limited(decision: RateLimitDecision) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="operator rate limit exceeded",
        headers={
            "Retry-After": str(decision.retry_after_seconds),
            "RateLimit-Limit": str(decision.limit),
            "RateLimit-Remaining": str(decision.remaining),
        },
    )


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid operator credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
