"""Payload-free graph connectivity and projection-lag health evaluation."""

import asyncio
from datetime import UTC, datetime

from chakravyuh.application.ports import GraphProjectionRepository, GraphProjector
from chakravyuh.domain.projections import GraphProjectionHealth, ProjectionLag


class CheckGraphProjectionHealth:
    """Fail closed when Neo4j is unreachable, dead-lettered, or too stale."""

    def __init__(
        self,
        repository: GraphProjectionRepository,
        projector: GraphProjector,
        *,
        lag_threshold_seconds: float,
        connectivity_timeout_seconds: float,
    ) -> None:
        self._repository = repository
        self._projector = projector
        self._lag_threshold_seconds = lag_threshold_seconds
        self._connectivity_timeout_seconds = connectivity_timeout_seconds

    async def execute(self) -> GraphProjectionHealth:
        try:
            lag = await self._repository.lag()
        except Exception:
            return GraphProjectionHealth(
                healthy=False,
                neo4j_reachable=False,
                lag=ProjectionLag(
                    pending_count=0,
                    processing_count=0,
                    dead_letter_count=0,
                    pending_rebuild_count=0,
                    max_version_lag=0,
                    oldest_unprojected_age_seconds=0,
                ),
                lag_threshold_seconds=self._lag_threshold_seconds,
                checked_at=datetime.now(UTC),
                reason="projection_lag_unavailable",
            )
        neo4j_reachable = True
        try:
            await asyncio.wait_for(
                self._projector.verify_connectivity(),
                timeout=self._connectivity_timeout_seconds,
            )
        except Exception:
            neo4j_reachable = False

        reason: str | None = None
        if not neo4j_reachable:
            reason = "neo4j_unreachable"
        elif lag.dead_letter_count > 0:
            reason = "projection_dead_letter"
        elif lag.pending_rebuild_count > 0:
            reason = "projection_rebuild_pending"
        elif lag.oldest_unprojected_age_seconds > self._lag_threshold_seconds:
            reason = "projection_lag_exceeded"
        return GraphProjectionHealth(
            healthy=reason is None,
            neo4j_reachable=neo4j_reachable,
            lag=lag,
            lag_threshold_seconds=self._lag_threshold_seconds,
            checked_at=datetime.now(UTC),
            reason=reason,
        )
