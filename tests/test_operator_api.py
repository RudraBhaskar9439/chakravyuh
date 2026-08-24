"""Authenticated operator API boundary tests."""

import hashlib
from typing import Any
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from chakravyuh.api.main import create_app
from chakravyuh.config import Settings
from chakravyuh.domain.enums import IncidentStatus, OperatorScope
from chakravyuh.domain.operators import IncidentDetail, IncidentOverview, IncidentPage
from chakravyuh.infrastructure.rate_limiting import RateLimiterUnavailableError

TOKEN = "operator-test-token-with-enough-entropy"


class _ReadModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_list = False

    async def overview(self, **parameters: Any) -> IncidentOverview:
        self.calls.append(("overview", parameters))
        return IncidentOverview(
            status_counts=dict.fromkeys(IncidentStatus, 0),
            total_at_risk_subunits={},
            awaiting_diagnosis_count=0,
            diagnosis_dead_letter_count=0,
        )

    async def list_incidents(self, **parameters: Any) -> IncidentPage:
        self.calls.append(("list", parameters))
        if self.fail_list:
            raise ValueError("invalid cursor")
        return IncidentPage(items=())

    async def get_incident(
        self,
        incident_id: UUID,
        **parameters: Any,
    ) -> IncidentDetail | None:
        self.calls.append(("detail", {"incident_id": incident_id, **parameters}))
        return None


def _settings(
    *,
    configured: bool = True,
    scopes: list[OperatorScope] | None = None,
    auth_limit: int = 30,
) -> Settings:
    return Settings(
        environment="test",
        operator_token_hashes=(
            {"risk-operator": hashlib.sha256(TOKEN.encode()).hexdigest()} if configured else {}
        ),
        operator_principal_scopes=(
            {"risk-operator": scopes} if configured and scopes is not None else {}
        ),
        operator_auth_attempts_per_minute=auth_limit,
    )


def _client(settings: Settings, read_model: _ReadModel) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(
            app=create_app(settings, operator_read_model=read_model),
        ),
        base_url="http://test",
    )


async def test_operator_api_fails_closed_when_unconfigured_or_unauthorized() -> None:
    read_model = _ReadModel()
    async with _client(_settings(configured=False), read_model) as client:
        unavailable = await client.get("/v1/operator/overview")
    async with _client(_settings(), read_model) as client:
        missing = await client.get("/v1/operator/overview")
        invalid = await client.get(
            "/v1/operator/overview",
            headers={"Authorization": "Bearer incorrect"},
        )

    assert unavailable.status_code == 503
    assert missing.status_code == invalid.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert "incorrect" not in invalid.text
    assert read_model.calls == []


async def test_operator_overview_is_authenticated_audited_and_not_cacheable() -> None:
    read_model = _ReadModel()
    async with _client(_settings(), read_model) as client:
        response = await client.get(
            "/v1/operator/overview",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "X-Request-ID": "operator-request-1",
            },
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["awaiting_diagnosis_count"] == 0
    assert read_model.calls == [
        (
            "overview",
            {"principal_id": "risk-operator", "request_id": "operator-request-1"},
        )
    ]


async def test_operator_request_id_is_replaced_when_unbounded() -> None:
    read_model = _ReadModel()
    async with _client(_settings(), read_model) as client:
        response = await client.get(
            "/v1/operator/overview",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "X-Request-ID": "x" * 256,
            },
        )

    assert response.status_code == 200
    audited_request_id = read_model.calls[0][1]["request_id"]
    assert audited_request_id != "x" * 256
    assert len(audited_request_id) == 36


async def test_operator_list_validates_filters_and_hides_cursor_details() -> None:
    read_model = _ReadModel()
    async with _client(_settings(), read_model) as client:
        response = await client.get(
            "/v1/operator/incidents?status=detected&status=investigating&limit=20",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        invalid_status = await client.get(
            "/v1/operator/incidents?status=not-real",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        read_model.fail_list = True
        invalid_cursor = await client.get(
            "/v1/operator/incidents?cursor=opaque-invalid",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    assert read_model.calls[0][1]["statuses"] == ("detected", "investigating")
    assert read_model.calls[0][1]["limit"] == 20
    assert invalid_status.status_code == 422
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json() == {"detail": "invalid incident query"}


async def test_operator_detail_returns_generic_not_found() -> None:
    read_model = _ReadModel()
    incident_id = uuid4()
    async with _client(_settings(), read_model) as client:
        response = await client.get(
            f"/v1/operator/incidents/{incident_id}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "incident not found"}
    assert read_model.calls[0][1]["incident_id"] == incident_id


async def test_operator_scope_denial_happens_before_read_model() -> None:
    read_model = _ReadModel()
    settings = _settings(scopes=[OperatorScope.METRICS_READ])
    async with _client(settings, read_model) as client:
        response = await client.get(
            "/v1/operator/overview",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "operator permission denied"}
    assert read_model.calls == []


async def test_operator_authentication_is_rate_limited_by_client() -> None:
    read_model = _ReadModel()
    async with _client(_settings(auth_limit=2), read_model) as client:
        first = await client.get("/v1/operator/overview")
        second = await client.get(
            "/v1/operator/overview",
            headers={"Authorization": "Bearer wrong"},
        )
        limited = await client.get("/v1/operator/overview")

    assert first.status_code == second.status_code == 401
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]
    assert limited.headers["RateLimit-Limit"] == "2"
    assert limited.headers["RateLimit-Remaining"] == "0"


class _UnavailableLimiter:
    async def consume(self, *_args: Any, **_kwargs: Any) -> None:
        raise RateLimiterUnavailableError

    async def close(self) -> None:
        return None


async def test_operator_authentication_fails_closed_when_limiter_is_unavailable() -> None:
    read_model = _ReadModel()
    app = create_app(
        _settings(),
        operator_read_model=read_model,
        operator_rate_limiter=_UnavailableLimiter(),  # type: ignore[arg-type]
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/operator/overview",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "operator authentication unavailable"}
    assert read_model.calls == []


async def test_metrics_endpoint_has_separate_scope_and_template_labels() -> None:
    read_model = _ReadModel()
    settings = _settings(scopes=[OperatorScope.METRICS_READ])
    async with _client(settings, read_model) as client:
        await client.get("/health/live")
        response = await client.get(
            "/internal/metrics",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Type"].startswith("text/plain")
    assert 'route="/health/live",status="200"} 1' in response.text
    assert 'environment="test",version="0.10.0"' in response.text
