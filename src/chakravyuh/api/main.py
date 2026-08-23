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
from chakravyuh.config import Settings, get_settings
from chakravyuh.logging import configure_logging

logger = structlog.get_logger(__name__)


def _lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await logger.ainfo(
            "application_started",
            environment=settings.environment,
            version=__version__,
        )
        yield
        await logger.ainfo("application_stopped")

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an isolated application instance for production and tests."""
    resolved_settings = settings or get_settings()
    configure_logging(
        resolved_settings.log_level,
        json_logs=resolved_settings.environment != "local",
    )

    app = FastAPI(
        title="Chakravyuh API",
        summary="Self-healing money graph and payment recovery control plane",
        version=__version__,
        docs_url="/docs" if not resolved_settings.is_production else None,
        redoc_url=None,
        lifespan=_lifespan(resolved_settings),
    )
    app.state.settings = resolved_settings
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
