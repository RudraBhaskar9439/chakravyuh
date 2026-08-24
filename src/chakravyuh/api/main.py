"""FastAPI application factory and process entrypoint."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from uuid import uuid4

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from chakravyuh import __version__
from chakravyuh.api.health import router as health_router
from chakravyuh.api.webhooks import router as webhook_router
from chakravyuh.application.ports import WebhookEventStore
from chakravyuh.application.webhook_ingestion import IngestVerifiedWebhook
from chakravyuh.config import Settings, get_settings
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.webhook_event_store import PostgresWebhookEventStore
from chakravyuh.logging import configure_logging

logger = structlog.get_logger(__name__)


def _lifespan(
    settings: Settings,
    database: Database,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await logger.ainfo(
            "application_started",
            environment=settings.environment,
            version=__version__,
        )
        try:
            yield
        finally:
            await database.close()
            await logger.ainfo("application_stopped")

    return lifespan


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    webhook_event_store: WebhookEventStore | None = None,
) -> FastAPI:
    """Create an isolated application instance for production and tests."""
    resolved_settings = settings or get_settings()
    configure_logging(
        resolved_settings.log_level,
        json_logs=resolved_settings.environment != "local",
    )
    resolved_database = database or Database(resolved_settings)
    resolved_webhook_store = webhook_event_store or PostgresWebhookEventStore(resolved_database)

    app = FastAPI(
        title="Chakravyuh API",
        summary="Self-healing money graph and payment recovery control plane",
        version=__version__,
        docs_url="/docs" if not resolved_settings.is_production else None,
        redoc_url=None,
        lifespan=_lifespan(resolved_settings, resolved_database),
    )
    app.state.settings = resolved_settings
    app.state.database = resolved_database
    app.state.ingest_webhook = IngestVerifiedWebhook(resolved_webhook_store)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    app.include_router(health_router)
    app.include_router(webhook_router)
    return app


def run() -> None:
    """Run the API using configured network settings."""
    settings = get_settings()
    uvicorn.run(
        "chakravyuh.api.main:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
