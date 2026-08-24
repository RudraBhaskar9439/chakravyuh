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
from chakravyuh.api.actions import router as action_router
from chakravyuh.api.health import router as health_router
from chakravyuh.api.operators import router as operator_router
from chakravyuh.api.webhooks import router as webhook_router
from chakravyuh.application.ports import (
    ActionControlPlane,
    GraphProjector,
    OperatorReadModel,
    RazorpayPaymentGateway,
    WebhookEventStore,
)
from chakravyuh.application.projection_health import CheckGraphProjectionHealth
from chakravyuh.application.recovery_actions import RecoveryActionControlPlane
from chakravyuh.application.webhook_ingestion import IngestVerifiedWebhook
from chakravyuh.config import Settings, get_settings
from chakravyuh.domain.action_policy import DeterministicRecoveryPolicy, RecoveryPolicyConfig
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.neo4j.projector import Neo4jPaymentGraphProjector
from chakravyuh.infrastructure.postgres.action_repository import (
    PostgresRecoveryActionRepository,
)
from chakravyuh.infrastructure.postgres.graph_projection_repository import (
    PostgresGraphProjectionRepository,
)
from chakravyuh.infrastructure.postgres.operator_read_model import PostgresOperatorReadModel
from chakravyuh.infrastructure.postgres.webhook_event_store import PostgresWebhookEventStore
from chakravyuh.infrastructure.razorpay.actions import (
    DisabledRazorpayPaymentGateway,
    RazorpayTestModePaymentGateway,
)
from chakravyuh.logging import configure_logging

logger = structlog.get_logger(__name__)


def _lifespan(
    settings: Settings,
    database: Database,
    graph_projector: GraphProjector,
    payment_gateway: RazorpayPaymentGateway,
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
            try:
                await payment_gateway.close()
            finally:
                await graph_projector.close()
                await database.close()
            await logger.ainfo("application_stopped")

    return lifespan


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    webhook_event_store: WebhookEventStore | None = None,
    graph_projector: GraphProjector | None = None,
    operator_read_model: OperatorReadModel | None = None,
    payment_gateway: RazorpayPaymentGateway | None = None,
    action_control_plane: ActionControlPlane | None = None,
) -> FastAPI:
    """Create an isolated application instance for production and tests."""
    resolved_settings = settings or get_settings()
    configure_logging(
        resolved_settings.log_level,
        json_logs=resolved_settings.environment != "local",
    )
    resolved_database = database or Database(resolved_settings)
    resolved_webhook_store = webhook_event_store or PostgresWebhookEventStore(resolved_database)
    resolved_graph_projector = graph_projector or Neo4jPaymentGraphProjector(resolved_settings)
    projection_repository = PostgresGraphProjectionRepository(resolved_database)
    resolved_operator_read_model = operator_read_model or PostgresOperatorReadModel(
        resolved_database
    )
    resolved_payment_gateway = payment_gateway or (
        RazorpayTestModePaymentGateway(resolved_settings)
        if resolved_settings.razorpay_test_actions_configured
        else DisabledRazorpayPaymentGateway()
    )
    resolved_action_control_plane = action_control_plane or RecoveryActionControlPlane(
        PostgresRecoveryActionRepository(resolved_database),
        DeterministicRecoveryPolicy(
            RecoveryPolicyConfig(
                actions_enabled=resolved_settings.razorpay_actions_enabled,
                test_credentials=resolved_settings.razorpay_test_actions_configured,
                merchant_id=resolved_settings.razorpay_merchant_id,
                maximum_capture_subunits=resolved_settings.action_max_capture_subunits,
                minimum_capture_confidence=(resolved_settings.action_minimum_capture_confidence),
            )
        ),
        resolved_payment_gateway,
        proposal_ttl_seconds=resolved_settings.action_proposal_ttl_seconds,
        execution_lease_seconds=resolved_settings.action_execution_lease_seconds,
    )

    app = FastAPI(
        title="Chakravyuh API",
        summary="Self-healing money graph and payment recovery control plane",
        version=__version__,
        docs_url="/docs" if not resolved_settings.is_production else None,
        redoc_url=None,
        lifespan=_lifespan(
            resolved_settings,
            resolved_database,
            resolved_graph_projector,
            resolved_payment_gateway,
        ),
    )
    app.state.settings = resolved_settings
    app.state.database = resolved_database
    app.state.check_graph_projection_health = CheckGraphProjectionHealth(
        projection_repository,
        resolved_graph_projector,
        lag_threshold_seconds=resolved_settings.graph_projection_lag_threshold_seconds,
        connectivity_timeout_seconds=resolved_settings.neo4j_connection_timeout_seconds,
    )
    app.state.ingest_webhook = IngestVerifiedWebhook(resolved_webhook_store)
    app.state.operator_read_model = resolved_operator_read_model
    app.state.action_control_plane = resolved_action_control_plane
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
        supplied_request_id = request.headers.get("x-request-id", "").strip()
        request_id = supplied_request_id if 1 <= len(supplied_request_id) <= 255 else str(uuid4())
        request.state.request_id = request_id
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
    app.include_router(operator_router)
    app.include_router(action_router)
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
