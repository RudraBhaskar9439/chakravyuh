"""API process-boundary tests."""

from datetime import UTC, datetime
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from chakravyuh import __version__
from chakravyuh.api.main import create_app, run
from chakravyuh.config import Settings
from chakravyuh.domain.projections import GraphProjectionHealth, ProjectionLag


class ReadyDatabase:
    async def ping(self) -> None:
        return None


class StubGraphHealth:
    def __init__(self, *, healthy: bool) -> None:
        self.healthy = healthy

    async def execute(self) -> GraphProjectionHealth:
        return GraphProjectionHealth(
            healthy=self.healthy,
            neo4j_reachable=self.healthy,
            lag=ProjectionLag(
                pending_count=0,
                processing_count=0,
                dead_letter_count=0 if self.healthy else 1,
                pending_rebuild_count=0,
                max_version_lag=0 if self.healthy else 1,
                oldest_unprojected_age_seconds=0,
            ),
            lag_threshold_seconds=60,
            checked_at=datetime.now(UTC),
            reason=None if self.healthy else "projection_dead_letter",
        )


async def test_liveness_contract(test_settings: Settings) -> None:
    transport = ASGITransport(app=create_app(test_settings))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live", headers={"X-Request-ID": "request-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.json() == {
        "status": "ok",
        "service": "chakravyuh-api",
        "version": __version__,
        "environment": "test",
        "timestamp": response.json()["timestamp"],
        "checks": {"process": "ok"},
    }


async def test_liveness_generates_request_id(test_settings: Settings) -> None:
    transport = ASGITransport(app=create_app(test_settings))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


async def test_readiness_reports_postgres(test_settings: Settings) -> None:
    app = create_app(test_settings)
    app.state.database = ReadyDatabase()
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {"configuration": "ok", "postgres": "ok"}


async def test_readiness_fails_closed_when_postgres_is_unavailable(
    test_settings: Settings,
) -> None:
    class UnavailableDatabase:
        async def ping(self) -> None:
            raise RuntimeError("database unavailable")

    app = create_app(test_settings)
    app.state.database = UnavailableDatabase()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["checks"] == {"configuration": "ok", "postgres": "error"}


async def test_graph_health_reports_lag_without_identifiers(test_settings: Settings) -> None:
    app = create_app(test_settings)
    app.state.check_graph_projection_health = StubGraphHealth(healthy=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        healthy = await client.get("/health/graph")

    app.state.check_graph_projection_health = StubGraphHealth(healthy=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unhealthy = await client.get("/health/graph")

    assert healthy.status_code == 200
    assert healthy.json()["healthy"] is True
    assert unhealthy.status_code == 503
    assert unhealthy.json()["reason"] == "projection_dead_letter"
    assert "merchant" not in unhealthy.text


def test_production_disables_api_documentation() -> None:
    settings = Settings(environment="production", cors_origins=["https://operator.example"])
    app = create_app(settings)

    assert app.docs_url is None
    assert app.redoc_url is None


def test_run_uses_configured_bind_address(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CHAKRAVYUH_API_HOST", "127.0.0.1")
    monkeypatch.setenv("CHAKRAVYUH_API_PORT", "8123")

    with patch("chakravyuh.api.main.uvicorn.run") as uvicorn_run:
        run()

    uvicorn_run.assert_called_once_with(
        "chakravyuh.api.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=8123,
    )
