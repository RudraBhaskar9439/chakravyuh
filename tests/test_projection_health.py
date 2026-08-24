"""Projection health policy tests."""

from datetime import UTC, datetime

import pytest

from chakravyuh.application.projection_health import CheckGraphProjectionHealth
from chakravyuh.domain.projections import ProjectionLag


class HealthRepository:
    def __init__(self, lag: ProjectionLag, *, unavailable: bool = False) -> None:
        self.value = lag
        self.unavailable = unavailable

    async def lag(self) -> ProjectionLag:
        if self.unavailable:
            raise RuntimeError("postgres unavailable")
        return self.value


class HealthProjector:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    async def verify_connectivity(self) -> None:
        if self.unavailable:
            raise RuntimeError("unavailable")


def _lag(*, age: float = 0, dead: int = 0, rebuilds: int = 0) -> ProjectionLag:
    return ProjectionLag(
        pending_count=int(age > 0),
        processing_count=0,
        dead_letter_count=dead,
        pending_rebuild_count=rebuilds,
        max_version_lag=int(age > 0 or dead > 0),
        oldest_unprojected_at=datetime.now(UTC) if age or dead else None,
        oldest_unprojected_age_seconds=age,
    )


@pytest.mark.parametrize(
    ("lag", "unavailable", "healthy", "reason"),
    [
        (_lag(), False, True, None),
        (_lag(age=61), False, False, "projection_lag_exceeded"),
        (_lag(dead=1), False, False, "projection_dead_letter"),
        (_lag(rebuilds=1), False, False, "projection_rebuild_pending"),
        (_lag(), True, False, "neo4j_unreachable"),
    ],
)
async def test_projection_health_fails_closed(
    lag: ProjectionLag,
    unavailable: bool,
    healthy: bool,
    reason: str | None,
) -> None:
    result = await CheckGraphProjectionHealth(
        HealthRepository(lag),  # type: ignore[arg-type]
        HealthProjector(unavailable=unavailable),  # type: ignore[arg-type]
        lag_threshold_seconds=60,
        connectivity_timeout_seconds=1,
    ).execute()

    assert result.healthy is healthy
    assert result.reason == reason


async def test_projection_health_fails_closed_when_lag_query_fails() -> None:
    result = await CheckGraphProjectionHealth(
        HealthRepository(_lag(), unavailable=True),  # type: ignore[arg-type]
        HealthProjector(),  # type: ignore[arg-type]
        lag_threshold_seconds=60,
        connectivity_timeout_seconds=1,
    ).execute()

    assert result.healthy is False
    assert result.reason == "projection_lag_unavailable"
