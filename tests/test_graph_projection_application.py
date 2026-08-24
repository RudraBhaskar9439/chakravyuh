"""Application-level at-least-once graph projection tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from neo4j.exceptions import ServiceUnavailable

from chakravyuh.application.graph_projection import (
    ProcessGraphProjectionBatch,
    _projection_error_code,
)
from chakravyuh.domain.errors import ProjectionLeaseLostError, StaleGraphProjectionError
from chakravyuh.domain.projections import GraphProjectionReceipt, ProjectionWorkClaim


def _claim(correlation_id: str, attempt: int = 1) -> ProjectionWorkClaim:
    return ProjectionWorkClaim(
        merchant_id="merchant-1",
        correlation_id=correlation_id,
        target_version=1,
        state_generation=1,
        projection_epoch=datetime.now(UTC),
        attempt_number=attempt,
        lease_owner="worker-1",
        leased_until=datetime.now(UTC) + timedelta(seconds=30),
    )


def _receipt(claim: ProjectionWorkClaim) -> GraphProjectionReceipt:
    return GraphProjectionReceipt(
        merchant_id=claim.merchant_id,
        correlation_id=claim.correlation_id,
        state_generation=1,
        projection_epoch=claim.projection_epoch,
        state_hash="a" * 64,
        entity_count=2,
        event_count=3,
        projected_at=datetime.now(UTC),
        projection_id=uuid4(),
    )


class FakeRepository:
    def __init__(
        self,
        claims: list[ProjectionWorkClaim],
        *,
        dead_letter: bool = False,
        lose_on: str | None = None,
    ) -> None:
        self.claims = claims
        self.dead_letter = dead_letter
        self.completed: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.lose_on = lose_on

    async def claim_batch(self, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs == {"worker_id": "worker-1", "batch_size": 10, "lease_seconds": 30}
        return self.claims

    async def load(self, claim):  # type: ignore[no-untyped-def]
        return claim

    async def complete(self, claim, receipt):  # type: ignore[no-untyped-def]
        if self.lose_on == "complete":
            raise ProjectionLeaseLostError("test lease expired")
        assert receipt.correlation_id == claim.correlation_id
        self.completed.append(claim.correlation_id)

    async def fail(self, claim, **kwargs):  # type: ignore[no-untyped-def]
        if self.lose_on == "fail":
            raise ProjectionLeaseLostError("test lease expired")
        self.failed.append((claim.correlation_id, kwargs["error_code"]))
        return self.dead_letter


class FakeProjector:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()

    async def project(self, claim):  # type: ignore[no-untyped-def]
        if claim.correlation_id in self.failing:
            raise ServiceUnavailable("test-only unavailable")
        return _receipt(claim)


async def test_projection_batch_isolates_retryable_item_failure() -> None:
    claims = [_claim("order-fail"), _claim("order-ok")]
    repository = FakeRepository(claims)
    processor = ProcessGraphProjectionBatch(
        repository,  # type: ignore[arg-type]
        FakeProjector({"order-fail"}),  # type: ignore[arg-type]
        worker_id="worker-1",
        batch_size=10,
        lease_seconds=30,
        max_failures=5,
        retry_delay_seconds=1,
    )

    result = await processor.execute()

    assert result.claimed == 2
    assert result.completed == 1
    assert result.retried == 1
    assert result.dead_lettered == 0
    assert repository.completed == ["order-ok"]
    assert repository.failed == [("order-fail", "neo4j_unavailable")]


async def test_projection_batch_reports_dead_letter_and_idle() -> None:
    claim = _claim("order-dead")
    repository = FakeRepository([claim], dead_letter=True)
    failed = ProcessGraphProjectionBatch(
        repository,  # type: ignore[arg-type]
        FakeProjector({"order-dead"}),  # type: ignore[arg-type]
        worker_id="worker-1",
        batch_size=10,
        lease_seconds=30,
        max_failures=1,
        retry_delay_seconds=0,
    )

    assert (await failed.execute()).dead_lettered == 1

    repository.claims = []
    idle = await failed.execute()
    assert idle.claimed == 0
    assert idle.completed == 0


def test_projection_error_codes_never_include_exception_messages() -> None:
    class CustomNeo4jError(Exception):
        __module__ = "neo4j.custom"

    assert _projection_error_code(CustomNeo4jError("secret")) == "neo4j_projection_rejected"
    assert _projection_error_code(StaleGraphProjectionError("secret")) == "neo4j_stale_generation"
    assert _projection_error_code(RuntimeError("secret")) == "projection_internal_error"


async def test_projection_batch_isolates_lost_leases() -> None:
    successful_claim = _claim("order-finished")
    complete_lost = ProcessGraphProjectionBatch(
        FakeRepository([successful_claim], lose_on="complete"),  # type: ignore[arg-type]
        FakeProjector(),  # type: ignore[arg-type]
        worker_id="worker-1",
        batch_size=10,
        lease_seconds=30,
        max_failures=5,
        retry_delay_seconds=1,
    )
    failed_claim = _claim("order-failed")
    fail_lost = ProcessGraphProjectionBatch(
        FakeRepository([failed_claim], lose_on="fail"),  # type: ignore[arg-type]
        FakeProjector({"order-failed"}),  # type: ignore[arg-type]
        worker_id="worker-1",
        batch_size=10,
        lease_seconds=30,
        max_failures=5,
        retry_delay_seconds=1,
    )

    assert (await complete_lost.execute()).lease_lost == 1
    assert (await fail_lost.execute()).lease_lost == 1
