"""Real PostgreSQL and Neo4j proofs for the leased graph projection."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from neo4j import AsyncGraphDatabase
from pydantic import SecretStr
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from chakravyuh.application.graph_projection import ProcessGraphProjectionBatch
from chakravyuh.application.graph_rebuild import FinalizeGraphRebuilds
from chakravyuh.config import Settings
from chakravyuh.domain.enums import EventSource, GraphProjectionStatus
from chakravyuh.domain.errors import ProjectionLeaseLostError, StaleGraphProjectionError
from chakravyuh.domain.journeys import TemporalPaymentJourneyReducer
from chakravyuh.domain.projections import (
    GraphProjectionReceipt,
    GraphRebuildCandidate,
    GraphRebuildReceipt,
    ProjectionWorkClaim,
)
from chakravyuh.domain.webhooks import RawWebhookEvent
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.neo4j.projector import Neo4jPaymentGraphProjector
from chakravyuh.infrastructure.postgres.graph_projection_repository import (
    PostgresGraphProjectionRepository,
)
from chakravyuh.infrastructure.postgres.journey_reduction_repository import (
    PostgresJourneyReductionRepository,
)
from chakravyuh.infrastructure.postgres.normalization_repository import (
    PostgresNormalizationRepository,
)
from chakravyuh.infrastructure.postgres.tables import (
    graph_projection_attempts,
    graph_projection_rebuild_completions,
    graph_projection_rebuilds,
    graph_projection_work,
    payment_journey_states,
)
from chakravyuh.infrastructure.postgres.webhook_event_store import PostgresWebhookEventStore
from chakravyuh.infrastructure.razorpay.normalizer import RazorpayWebhookNormalizer

TEST_POSTGRES_DSN = os.environ.get("CHAKRAVYUH_TEST_POSTGRES_DSN")
TEST_NEO4J_URI = os.environ.get("CHAKRAVYUH_TEST_NEO4J_URI")
TEST_NEO4J_PASSWORD = os.environ.get(
    "CHAKRAVYUH_TEST_NEO4J_PASSWORD",
    "local-development-only",
)
pytestmark = pytest.mark.skipif(
    TEST_POSTGRES_DSN is None or TEST_NEO4J_URI is None,
    reason="PostgreSQL and Neo4j test endpoints are required for graph integration proofs",
)


def _settings() -> Settings:
    assert TEST_POSTGRES_DSN is not None
    assert TEST_NEO4J_URI is not None
    return Settings(
        environment="test",
        postgres_dsn=TEST_POSTGRES_DSN,
        neo4j_uri=TEST_NEO4J_URI,
        neo4j_password=SecretStr(TEST_NEO4J_PASSWORD),
    )


def _database() -> Database:
    return Database(_settings())


def _raw_order(merchant_id: str, order_id: str) -> RawWebhookEvent:
    now = datetime.now(UTC)
    payload = {
        "event": "order.created",
        "payload": {
            "order": {
                "entity": {
                    "id": order_id,
                    "status": "created",
                    "amount": 10_000,
                    "amount_paid": 0,
                    "amount_due": 10_000,
                    "currency": "INR",
                }
            }
        },
    }
    return RawWebhookEvent(
        merchant_id=merchant_id,
        source=EventSource.RAZORPAY_WEBHOOK,
        source_event_id=f"event-{uuid4()}",
        event_type="order.created",
        account_id="test-account",
        occurred_at=now,
        observed_at=now,
        payload=payload,
        raw_body=json.dumps(payload, sort_keys=True).encode(),
    )


async def _create_states(
    database: Database,
    projector: Neo4jPaymentGraphProjector,
    count: int,
) -> list[tuple[str, str]]:
    normalizer = PostgresNormalizationRepository(database)
    while (
        await normalizer.process_batch(
            normalizer=RazorpayWebhookNormalizer(),
            worker_id="graph-test-normalizer",
            batch_size=500,
        )
    ).claimed:
        pass
    reducer = PostgresJourneyReductionRepository(database)
    while (
        await reducer.process_batch(
            reducer=TemporalPaymentJourneyReducer(),
            worker_id="graph-test-reducer",
            batch_size=500,
            max_events_per_journey=100_000,
        )
    ).claimed:
        pass
    await _drain_graph(database, projector)

    store = PostgresWebhookEventStore(database)
    identities: list[tuple[str, str]] = []
    for _ in range(count):
        merchant_id = f"merchant-{uuid4()}"
        order_id = f"order_{uuid4().hex}"
        assert await store.append(_raw_order(merchant_id, order_id)) is True
        identities.append((merchant_id, order_id))
    while (
        await normalizer.process_batch(
            normalizer=RazorpayWebhookNormalizer(),
            worker_id="graph-test-normalizer",
            batch_size=500,
        )
    ).claimed:
        pass
    while (
        await reducer.process_batch(
            reducer=TemporalPaymentJourneyReducer(),
            worker_id="graph-test-reducer",
            batch_size=500,
            max_events_per_journey=100_000,
        )
    ).claimed:
        pass
    return identities


async def _drain_graph(
    database: Database,
    projector: Neo4jPaymentGraphProjector,
    *,
    finalize: bool = True,
) -> None:
    processor = ProcessGraphProjectionBatch(
        PostgresGraphProjectionRepository(database),
        projector,
        worker_id="graph-test-drain",
        batch_size=500,
        lease_seconds=30,
        max_failures=5,
        retry_delay_seconds=0,
    )
    while (await processor.execute()).claimed:
        pass
    if finalize:
        finalizer = FinalizeGraphRebuilds(
            PostgresGraphProjectionRepository(database),
            projector,
        )
        while (await finalizer.execute()).candidates:
            pass


async def _graph_counts(merchant_id: str) -> tuple[int, int, int]:
    assert TEST_NEO4J_URI is not None
    driver = AsyncGraphDatabase.driver(
        TEST_NEO4J_URI,
        auth=("neo4j", TEST_NEO4J_PASSWORD),
    )
    try:
        records, _, _ = await driver.execute_query(
            """
            MATCH (merchant:Merchant {merchant_id: $merchant_id})-[:OWNS]->(journey)
            OPTIONAL MATCH (journey)-[:CONTAINS]->(entity)
            OPTIONAL MATCH (journey)-[:HAS_EVENT]->(event)
            RETURN count(DISTINCT journey) AS journeys,
                   count(DISTINCT entity) AS entities,
                   count(DISTINCT event) AS events
            """,
            merchant_id=merchant_id,
            database_="neo4j",
        )
    finally:
        await driver.close()
    record = records[0]
    return record["journeys"], record["entities"], record["events"]


async def _graph_generation(merchant_id: str) -> int:
    assert TEST_NEO4J_URI is not None
    driver = AsyncGraphDatabase.driver(
        TEST_NEO4J_URI,
        auth=("neo4j", TEST_NEO4J_PASSWORD),
    )
    try:
        records, _, _ = await driver.execute_query(
            """
            MATCH (:Merchant {merchant_id: $merchant_id})-[:OWNS]->(journey)
            RETURN journey.state_generation AS generation
            """,
            merchant_id=merchant_id,
            database_="neo4j",
        )
    finally:
        await driver.close()
    return int(records[0]["generation"])


async def _delete_merchant_graph(merchant_id: str) -> None:
    assert TEST_NEO4J_URI is not None
    driver = AsyncGraphDatabase.driver(
        TEST_NEO4J_URI,
        auth=("neo4j", TEST_NEO4J_PASSWORD),
    )
    try:
        await driver.execute_query(
            "MATCH (node {merchant_id: $merchant_id}) DETACH DELETE node",
            merchant_id=merchant_id,
            database_="neo4j",
        )
    finally:
        await driver.close()


async def _create_ghost_graph() -> str:
    assert TEST_NEO4J_URI is not None
    merchant_id = f"ghost-{uuid4()}"
    driver = AsyncGraphDatabase.driver(
        TEST_NEO4J_URI,
        auth=("neo4j", TEST_NEO4J_PASSWORD),
    )
    try:
        await driver.execute_query(
            """
            CREATE (merchant:Merchant {key: $merchant_id, merchant_id: $merchant_id})
            CREATE (journey:PaymentJourney {
                key: $journey_id,
                merchant_id: $merchant_id,
                projection_epoch_us: 0,
                state_generation: 99
            })
            CREATE (merchant)-[:OWNS]->(journey)
            """,
            merchant_id=merchant_id,
            journey_id=f"journey-{uuid4()}",
            database_="neo4j",
        )
    finally:
        await driver.close()
    return merchant_id


async def test_end_to_end_projection_checkpoints_only_after_graph_commit() -> None:
    database = _database()
    projector = Neo4jPaymentGraphProjector(_settings())
    try:
        await projector.initialize_schema()
        await _drain_graph(database, projector)
        ((merchant_id, correlation_id),) = await _create_states(database, projector, 1)
        processor = ProcessGraphProjectionBatch(
            PostgresGraphProjectionRepository(database),
            projector,
            worker_id="graph-worker",
            batch_size=1,
            lease_seconds=30,
            max_failures=5,
            retry_delay_seconds=0,
        )

        result = await processor.execute()

        assert result.completed == 1
        assert await _graph_counts(merchant_id) == (1, 1, 1)
        async with database.session_factory() as session:
            work = (
                (
                    await session.execute(
                        select(graph_projection_work).where(
                            graph_projection_work.c.merchant_id == merchant_id,
                            graph_projection_work.c.correlation_id == correlation_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            attempts = await session.scalar(
                select(func.count())
                .select_from(graph_projection_attempts)
                .where(graph_projection_attempts.c.merchant_id == merchant_id)
            )
        assert work["status"] == GraphProjectionStatus.COMPLETED.value
        assert work["applied_version"] == work["target_version"]
        assert attempts == 1
    finally:
        await projector.close()
        await database.close()


async def test_repeating_graph_commit_is_idempotent_before_checkpoint() -> None:
    database = _database()
    projector = Neo4jPaymentGraphProjector(_settings())
    repository = PostgresGraphProjectionRepository(database)
    try:
        await projector.initialize_schema()
        await _drain_graph(database, projector)
        ((merchant_id, correlation_id),) = await _create_states(database, projector, 1)
        claim = (
            await repository.claim_batch(worker_id="crash-worker", batch_size=1, lease_seconds=30)
        )[0]
        projection = await repository.load(claim)

        first = await projector.project(projection)
        second = await projector.project(projection)
        await repository.complete(claim, second)

        assert first.projection_id == second.projection_id
        assert await _graph_counts(merchant_id) == (1, 1, 1)
        assert correlation_id == projection.state.correlation_id
    finally:
        await projector.close()
        await database.close()


async def test_neo4j_rejects_an_expired_writer_after_a_newer_generation() -> None:
    database = _database()
    projector = Neo4jPaymentGraphProjector(_settings())
    repository = PostgresGraphProjectionRepository(database)
    merchant_id: str | None = None
    try:
        await projector.initialize_schema()
        await _drain_graph(database, projector)
        ((merchant_id, _),) = await _create_states(database, projector, 1)
        claim = (
            await repository.claim_batch(worker_id="stale-worker", batch_size=1, lease_seconds=30)
        )[0]
        projection = await repository.load(claim)
        newer = projection.model_copy(update={"state_generation": projection.state_generation + 1})

        newer_receipt = await projector.project(newer)
        with pytest.raises(StaleGraphProjectionError, match="stale"):
            await projector.project(projection)
        await repository.complete(claim, newer_receipt)

        assert await _graph_generation(merchant_id) == newer.state_generation
    finally:
        if merchant_id is not None:
            await _delete_merchant_graph(merchant_id)
        await projector.close()
        await database.close()


async def test_expired_lease_is_reclaimed_and_old_owner_cannot_checkpoint() -> None:
    database = _database()
    projector = Neo4jPaymentGraphProjector(_settings())
    repository = PostgresGraphProjectionRepository(database)
    try:
        await projector.initialize_schema()
        await _drain_graph(database, projector)
        ((merchant_id, correlation_id),) = await _create_states(database, projector, 1)
        first = (
            await repository.claim_batch(worker_id="first-worker", batch_size=1, lease_seconds=30)
        )[0]
        async with database.transaction() as session:
            await session.execute(
                update(graph_projection_work)
                .where(
                    graph_projection_work.c.merchant_id == merchant_id,
                    graph_projection_work.c.correlation_id == correlation_id,
                )
                .values(lease_expires_at=func.now() - timedelta(seconds=1))
            )
        with pytest.raises(ProjectionLeaseLostError, match="no longer owned"):
            await repository.complete(first, await projector.project(await repository.load(first)))
        second = (
            await repository.claim_batch(worker_id="second-worker", batch_size=1, lease_seconds=30)
        )[0]

        assert second.attempt_number == first.attempt_number + 1
        with pytest.raises(ProjectionLeaseLostError, match="no longer owned"):
            await repository.fail(
                first,
                error_code="neo4j_unavailable",
                max_failures=5,
                retry_delay_seconds=0,
            )
        projection = await repository.load(second)
        await repository.complete(second, await projector.project(projection))
    finally:
        await projector.close()
        await database.close()


async def test_state_change_during_projection_leaves_a_new_pending_version() -> None:
    database = _database()
    projector = Neo4jPaymentGraphProjector(_settings())
    repository = PostgresGraphProjectionRepository(database)
    try:
        await projector.initialize_schema()
        await _drain_graph(database, projector)
        ((merchant_id, correlation_id),) = await _create_states(database, projector, 1)
        claim = (
            await repository.claim_batch(worker_id="slow-worker", batch_size=1, lease_seconds=30)
        )[0]
        projection = await repository.load(claim)

        async with database.transaction() as session:
            await session.execute(
                update(payment_journey_states)
                .where(
                    payment_journey_states.c.merchant_id == merchant_id,
                    payment_journey_states.c.correlation_id == correlation_id,
                )
                .values(updated_at=func.now())
            )
        await repository.complete(claim, await projector.project(projection))

        async with database.session_factory() as session:
            work = (
                (
                    await session.execute(
                        select(graph_projection_work).where(
                            graph_projection_work.c.merchant_id == merchant_id,
                            graph_projection_work.c.correlation_id == correlation_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
        assert work["status"] == GraphProjectionStatus.PENDING.value
        assert work["target_version"] == claim.target_version + 1
        assert work["applied_version"] == claim.target_version
        await _drain_graph(database, projector)
    finally:
        await projector.close()
        await database.close()


async def test_concurrent_claimers_partition_correlations() -> None:
    database = _database()
    projector = Neo4jPaymentGraphProjector(_settings())
    repository = PostgresGraphProjectionRepository(database)
    try:
        await projector.initialize_schema()
        await _drain_graph(database, projector)
        identities = await _create_states(database, projector, 6)

        batches = await asyncio.gather(
            *(
                repository.claim_batch(
                    worker_id=f"worker-{number}",
                    batch_size=2,
                    lease_seconds=30,
                )
                for number in range(3)
            )
        )
        claims = [claim for batch in batches for claim in batch]

        assert len(claims) == 6
        assert len({(claim.merchant_id, claim.correlation_id) for claim in claims}) == 6
        assert set(identities) == {(claim.merchant_id, claim.correlation_id) for claim in claims}
        for claim in claims:
            projection = await repository.load(claim)
            await repository.complete(claim, await projector.project(projection))
    finally:
        await projector.close()
        await database.close()


async def test_failures_dead_letter_lag_and_audited_rebuild_recovers() -> None:
    database = _database()
    projector = Neo4jPaymentGraphProjector(_settings())
    repository = PostgresGraphProjectionRepository(database)
    try:
        await projector.initialize_schema()
        await _drain_graph(database, projector)
        baseline_dead_letters = (await repository.lag()).dead_letter_count
        await _create_states(database, projector, 1)
        first = (
            await repository.claim_batch(worker_id="failing-worker", batch_size=1, lease_seconds=30)
        )[0]
        assert not await repository.fail(
            first,
            error_code="neo4j_unavailable",
            max_failures=2,
            retry_delay_seconds=0,
        )
        second = (
            await repository.claim_batch(worker_id="failing-worker", batch_size=1, lease_seconds=30)
        )[0]
        assert await repository.fail(
            second,
            error_code="neo4j_unavailable",
            max_failures=2,
            retry_delay_seconds=0,
        )

        lag = await repository.lag()
        assert lag.dead_letter_count == baseline_dead_letters + 1
        assert lag.max_version_lag >= 1
        ghost_merchant_id = await _create_ghost_graph()

        rebuild_id, journey_count = await repository.request_rebuild(
            requested_by="operator@example.test",
            reason="Neo4j recovery reviewed and connectivity restored.",
        )
        assert journey_count >= 1
        assert await repository.finalizable_rebuilds(limit=10) == []
        await _drain_graph(database, projector, finalize=False)
        assert (await repository.lag()).pending_rebuild_count >= 1
        (candidate,) = await repository.finalizable_rebuilds(limit=10)
        finalization = await FinalizeGraphRebuilds(repository, projector).execute()
        assert finalization.completed >= 1
        assert (await repository.lag()).dead_letter_count == 0
        assert (await repository.lag()).pending_rebuild_count == 0
        assert await _graph_counts(ghost_merchant_id) == (0, 0, 0)
        async with database.session_factory() as session:
            rebuild = (
                (
                    await session.execute(
                        select(graph_projection_rebuilds).where(
                            graph_projection_rebuilds.c.rebuild_id == rebuild_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            completion_count = await session.scalar(
                select(func.count())
                .select_from(graph_projection_rebuild_completions)
                .where(graph_projection_rebuild_completions.c.rebuild_id == rebuild_id)
            )
        assert rebuild["requested_by"] == "operator@example.test"
        assert completion_count == 1
        duplicate_receipt = GraphRebuildReceipt(
            rebuild_id=candidate.rebuild_id,
            projection_epoch=candidate.projection_epoch,
            journey_count_removed=0,
            entity_count_removed=0,
            event_count_removed=0,
            merchant_count_removed=0,
            pruned_at=datetime.now(UTC),
        )
        assert not await repository.complete_rebuild(candidate, duplicate_receipt)
    finally:
        await projector.close()
        await database.close()


async def test_projection_audit_tables_reject_mutation() -> None:
    database = _database()
    projector = Neo4jPaymentGraphProjector(_settings())
    repository = PostgresGraphProjectionRepository(database)
    try:
        await projector.initialize_schema()
        await _drain_graph(database, projector)
        await repository.request_rebuild(
            requested_by="security-test",
            reason="Create immutable graph rebuild evidence.",
        )
        await _drain_graph(database, projector)
        statements = [
            "DELETE FROM ledger.graph_projection_attempts",
            "UPDATE ledger.graph_projection_rebuilds SET journey_count = 1",
            "DELETE FROM ledger.graph_projection_rebuild_completions",
            "TRUNCATE ledger.graph_projection_attempts",
        ]
        for statement in statements:
            with pytest.raises(DBAPIError, match="append-only"):
                async with database.transaction() as session:
                    await session.execute(text(statement))
    finally:
        await projector.close()
        await database.close()


async def test_projection_repository_rejects_unsafe_bounds() -> None:
    database = _database()
    repository = PostgresGraphProjectionRepository(database)
    claim = ProjectionWorkClaim(
        merchant_id="missing-merchant",
        correlation_id="missing-correlation",
        target_version=1,
        state_generation=1,
        projection_epoch=datetime.now(UTC),
        attempt_number=1,
        lease_owner="worker",
        leased_until=datetime.now(UTC) + timedelta(seconds=30),
    )
    try:
        with pytest.raises(ValueError, match="worker_id"):
            await repository.claim_batch(worker_id=" ", batch_size=1, lease_seconds=1)
        with pytest.raises(ValueError, match="batch_size"):
            await repository.claim_batch(worker_id="worker", batch_size=0, lease_seconds=1)
        with pytest.raises(ValueError, match="lease_seconds"):
            await repository.claim_batch(worker_id="worker", batch_size=1, lease_seconds=0)
        with pytest.raises(ValueError, match="max_failures"):
            await repository.fail(
                claim,
                error_code="failure",
                max_failures=0,
                retry_delay_seconds=0,
            )
        with pytest.raises(ValueError, match="retry_delay_seconds"):
            await repository.fail(
                claim,
                error_code="failure",
                max_failures=1,
                retry_delay_seconds=-1,
            )
        with pytest.raises(ProjectionLeaseLostError, match="disappeared"):
            await repository.load(claim)
        mismatched = GraphProjectionReceipt(
            merchant_id="another-merchant",
            correlation_id=claim.correlation_id,
            state_generation=1,
            projection_epoch=claim.projection_epoch,
            state_hash="a" * 64,
            entity_count=0,
            event_count=0,
            projected_at=datetime.now(UTC),
            projection_id=uuid4(),
        )
        with pytest.raises(ValueError, match="does not match"):
            await repository.complete(claim, mismatched)
        older_receipt = mismatched.model_copy(update={"merchant_id": claim.merchant_id})
        with pytest.raises(ValueError, match="predates"):
            await repository.complete(
                claim.model_copy(update={"state_generation": 2}),
                older_receipt,
            )
        with pytest.raises(ValueError, match="requested_by"):
            await repository.request_rebuild(requested_by=" ", reason="safe")
        with pytest.raises(ValueError, match="limit"):
            await repository.finalizable_rebuilds(limit=0)
        candidate = GraphRebuildCandidate(
            rebuild_id=uuid4(),
            projection_epoch=datetime.now(UTC),
        )
        receipt = GraphRebuildReceipt(
            rebuild_id=uuid4(),
            projection_epoch=candidate.projection_epoch,
            journey_count_removed=0,
            entity_count_removed=0,
            event_count_removed=0,
            merchant_count_removed=0,
            pruned_at=datetime.now(UTC),
        )
        with pytest.raises(ValueError, match="does not match"):
            await repository.complete_rebuild(candidate, receipt)
    finally:
        await database.close()
