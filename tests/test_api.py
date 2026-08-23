"""API process-boundary tests."""

from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from chakravyuh import __version__
from chakravyuh.api.main import create_app, run
from chakravyuh.config import Settings


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


async def test_readiness_reports_only_registered_checks(test_settings: Settings) -> None:
    app = create_app(test_settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {"configuration": "ok"}


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
