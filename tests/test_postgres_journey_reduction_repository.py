"""Real PostgreSQL proofs for temporal journey materialization."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from chakravyuh.config import Settings
from chakravyuh.domain.enums import EntityType, EventSource, JourneyReductionStatus, PaymentStatus
from chakravyuh.domain.errors import JourneyReductionReplayNotAllowedError
from chakravyuh.domain.events import NormalizedEvent
from chakravyuh.domain.journeys import PaymentJourneyState, TemporalPaymentJourneyReducer
from chakravyuh.domain.webhooks import RawWebhookEvent
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.journey_reduction_repository import (
    PostgresJourneyReductionRepository,
)
from chakravyuh.infrastructure.postgres.normalization_repository import (
    PostgresNormalizationRepository,
)
from chakravyuh.infrastructure.postgres.tables import (
    journey_reduction_attempts,
    journey_reduction_replays,
    journey_reduction_work,
    payment_journey_revisions,
    payment_journey_states,
)
from chakravyuh.infrastructure.postgres.webhook_event_store import PostgresWebhookEventStore
from chakravyuh.infrastructure.razorpay.normalizer import RazorpayWebhookNormalizer

TEST_POSTGRES_DSN = os.environ.get("CHAKRAVYUH_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(
    TEST_POSTGRES_DSN is None,
    reason="CHAKRAVYUH_TEST_POSTGRES_DSN is required for PostgreSQL integration proofs",
)


class ExplodingReducer:
    version = "exploding-test-v1"

    def reduce(self, events: list[NormalizedEvent]) -> PaymentJourneyState:
        raise RuntimeError("simulated reducer failure")


def _database() -> Database:
    assert TEST_POSTGRES_DSN is not None
    return Database(Settings(environment="test", postgres_dsn=TEST_POSTGRES_DSN))


def _raw_event(
    *,
    merchant_id: str,
    order_id: str,
    event_type: str,
    entity_id: str,
    status: str,
    minute: int,
) -> RawWebhookEvent:
    family = event_type.partition(".")[0]
    started = datetime(2026, 8, 24, 10, tzinfo=UTC)
    entity: dict[str, object] = {
        "id": entity_id,
        "status": status,
        "amount": 10_000,
        "currency": "INR",
    }
    if family == "payment":
        entity["order_id"] = order_id
        entity["amount_refunded"] = 0
    payload = {"event": event_type, "payload": {family: {"entity": entity}}}
    source_event_id = f"evt_{uuid4()}"
    return RawWebhookEvent(
        merchant_id=merchant_id,
        source=EventSource.RAZORPAY_WEBHOOK,
        source_event_id=source_event_id,
        event_type=event_type,
        account_id="test-account",
        occurred_at=started + timedelta(minutes=minute),
        observed_at=started + timedelta(hours=1),
        payload=payload,
        raw_body=json.dumps(payload, sort_keys=True).encode(),
    )


async def _drain_normalization(database: Database) -> None:
    repository = PostgresNormalizationRepository(database)
    while True:
        result = await repository.process_batch(
            normalizer=RazorpayWebhookNormalizer(),
            worker_id="journey-test-normalizer",
            batch_size=500,
        )
        if result.claimed == 0:
            return


async def _drain_reductions(database: Database) -> None:
    repository = PostgresJourneyReductionRepository(database)
    while True:
        result = await repository.process_batch(
            reducer=TemporalPaymentJourneyReducer(),
            worker_id="journey-test-drain",
            batch_size=500,
            max_events_per_journey=100_000,
        )
        if result.claimed == 0:
            return


async def _append_events(database: Database, events: list[RawWebhookEvent]) -> None:
    store = PostgresWebhookEventStore(database)
    for event in events:
        assert await store.append(event) is True
    await _drain_normalization(database)


async def test_trigger_enqueues_and_materializes_complete_temporal_state() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    payment_id = f"pay_{uuid4().hex}"
    repository = PostgresJourneyReductionRepository(database)
    events = [
        _raw_event(
            merchant_id=merchant_id,
            order_id=order_id,
            event_type="order.created",
            entity_id=order_id,
            status="created",
            minute=0,
        ),
        _raw_event(
            merchant_id=merchant_id,
            order_id=order_id,
            event_type="payment.authorized",
            entity_id=payment_id,
            status="authorized",
            minute=1,
        ),
        _raw_event(
            merchant_id=merchant_id,
            order_id=order_id,
            event_type="payment.captured",
            entity_id=payment_id,
            status="captured",
            minute=2,
        ),
        _raw_event(
            merchant_id=merchant_id,
            order_id=order_id,
            event_type="order.paid",
            entity_id=order_id,
            status="paid",
            minute=3,
        ),
    ]
    try:
        await _drain_reductions(database)
        await _append_events(database, list(reversed(events)))

        result = await repository.process_batch(
            reducer=TemporalPaymentJourneyReducer(),
            worker_id="journey-worker",
            batch_size=10,
            max_events_per_journey=100,
        )
        state = await repository.get(merchant_id, order_id)

        assert result.completed == 1
        assert state is not None
        assert state.event_count == 4
        payment = next(
            entity for entity in state.entities if entity.entity.entity_type is EntityType.PAYMENT
        )
        assert payment.effective_payment_status is PaymentStatus.CAPTURED
        async with database.session_factory() as session:
            work = (
                (
                    await session.execute(
                        select(journey_reduction_work).where(
                            journey_reduction_work.c.merchant_id == merchant_id,
                            journey_reduction_work.c.correlation_id == order_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            revisions = await session.scalar(
                select(func.count())
                .select_from(payment_journey_revisions)
                .where(payment_journey_revisions.c.merchant_id == merchant_id)
            )
        assert work["generation"] == 4
        assert work["applied_generation"] == 4
        assert work["status"] == JourneyReductionStatus.COMPLETED.value
        assert revisions == 1
    finally:
        await database.close()


async def test_late_event_rebuilds_from_full_history_without_state_regression() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    payment_id = f"pay_{uuid4().hex}"
    repository = PostgresJourneyReductionRepository(database)
    authorized = _raw_event(
        merchant_id=merchant_id,
        order_id=order_id,
        event_type="payment.authorized",
        entity_id=payment_id,
        status="authorized",
        minute=2,
    )
    late_created = _raw_event(
        merchant_id=merchant_id,
        order_id=order_id,
        event_type="order.created",
        entity_id=order_id,
        status="created",
        minute=0,
    )
    try:
        await _drain_reductions(database)
        await _append_events(database, [authorized])
        await _drain_reductions(database)
        first = await repository.get(merchant_id, order_id)
        assert first is not None
        assert first.event_count == 1

        await _append_events(database, [late_created])
        await _drain_reductions(database)
        second = await repository.get(merchant_id, order_id)
        assert second is not None
        payment = next(
            entity for entity in second.entities if entity.entity.entity_type is EntityType.PAYMENT
        )

        assert second.event_count == 2
        assert second.latest_event_id == first.latest_event_id
        assert payment.effective_payment_status is PaymentStatus.AUTHORIZED
        async with database.session_factory() as session:
            revisions = await session.scalar(
                select(func.count())
                .select_from(payment_journey_revisions)
                .where(
                    payment_journey_revisions.c.merchant_id == merchant_id,
                    payment_journey_revisions.c.correlation_id == order_id,
                )
            )
        assert revisions == 2
    finally:
        await database.close()


async def test_concurrent_workers_claim_distinct_correlations() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    repository = PostgresJourneyReductionRepository(database)
    events = []
    for _ in range(6):
        order_id = f"order_{uuid4().hex}"
        events.append(
            _raw_event(
                merchant_id=merchant_id,
                order_id=order_id,
                event_type="order.created",
                entity_id=order_id,
                status="created",
                minute=0,
            )
        )
    try:
        await _drain_reductions(database)
        await _append_events(database, events)

        results = await asyncio.gather(
            *(
                repository.process_batch(
                    reducer=TemporalPaymentJourneyReducer(),
                    worker_id=f"journey-worker-{number}",
                    batch_size=2,
                    max_events_per_journey=100,
                )
                for number in range(3)
            )
        )

        assert sum(result.claimed for result in results) == 6
        async with database.session_factory() as session:
            states = await session.scalar(
                select(func.count())
                .select_from(payment_journey_states)
                .where(payment_journey_states.c.merchant_id == merchant_id)
            )
            attempts = await session.scalar(
                select(func.count())
                .select_from(journey_reduction_attempts)
                .where(journey_reduction_attempts.c.merchant_id == merchant_id)
            )
        assert states == 6
        assert attempts == 6
    finally:
        await database.close()


async def test_oversized_journey_dead_letters_then_audited_replay_recovers() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    payment_id = f"pay_{uuid4().hex}"
    repository = PostgresJourneyReductionRepository(database)
    events = [
        _raw_event(
            merchant_id=merchant_id,
            order_id=order_id,
            event_type="order.created",
            entity_id=order_id,
            status="created",
            minute=0,
        ),
        _raw_event(
            merchant_id=merchant_id,
            order_id=order_id,
            event_type="payment.authorized",
            entity_id=payment_id,
            status="authorized",
            minute=1,
        ),
    ]
    try:
        await _drain_reductions(database)
        await _append_events(database, events)
        failed = await repository.process_batch(
            reducer=TemporalPaymentJourneyReducer(),
            worker_id="bounded-worker",
            batch_size=1,
            max_events_per_journey=1,
        )
        assert failed.dead_lettered == 1
        assert await repository.get(merchant_id, order_id) is None

        replay_id = await repository.request_replay(
            merchant_id,
            order_id,
            requested_by="operator@example.test",
            reason="Reviewed event limit increased for this merchant.",
        )
        recovered = await repository.process_batch(
            reducer=TemporalPaymentJourneyReducer(),
            worker_id="bounded-worker",
            batch_size=1,
            max_events_per_journey=10,
        )

        assert recovered.completed == 1
        async with database.session_factory() as session:
            replay = (
                (
                    await session.execute(
                        select(journey_reduction_replays).where(
                            journey_reduction_replays.c.replay_id == replay_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            attempts = await session.scalar(
                select(func.count())
                .select_from(journey_reduction_attempts)
                .where(
                    journey_reduction_attempts.c.merchant_id == merchant_id,
                    journey_reduction_attempts.c.correlation_id == order_id,
                )
            )
        assert replay["requested_by"] == "operator@example.test"
        assert attempts == 2
    finally:
        await database.close()


async def test_completed_journey_can_be_audited_and_rebuilt_at_new_generation() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    repository = PostgresJourneyReductionRepository(database)
    event = _raw_event(
        merchant_id=merchant_id,
        order_id=order_id,
        event_type="order.created",
        entity_id=order_id,
        status="created",
        minute=0,
    )
    try:
        await _drain_reductions(database)
        await _append_events(database, [event])
        await _drain_reductions(database)
        first = await repository.get(merchant_id, order_id)
        assert first is not None

        await repository.request_replay(
            merchant_id,
            order_id,
            requested_by="release-operator",
            reason="Rebuild with the reviewed reducer release.",
        )
        await _drain_reductions(database)

        async with database.session_factory() as session:
            revisions = (
                (
                    await session.execute(
                        select(payment_journey_revisions)
                        .where(
                            payment_journey_revisions.c.merchant_id == merchant_id,
                            payment_journey_revisions.c.correlation_id == order_id,
                        )
                        .order_by(payment_journey_revisions.c.generation)
                    )
                )
                .mappings()
                .all()
            )
        assert [row["generation"] for row in revisions] == [1, 2]
        assert revisions[0]["state_hash"] == revisions[1]["state_hash"]
    finally:
        await database.close()


async def test_unexpected_failure_rolls_back_without_attempt_or_partial_state() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    repository = PostgresJourneyReductionRepository(database)
    event = _raw_event(
        merchant_id=merchant_id,
        order_id=order_id,
        event_type="order.created",
        entity_id=order_id,
        status="created",
        minute=0,
    )
    try:
        await _drain_reductions(database)
        await _append_events(database, [event])
        with pytest.raises(RuntimeError, match="simulated reducer failure"):
            await repository.process_batch(
                reducer=ExplodingReducer(),
                worker_id="exploding-worker",
                batch_size=1,
                max_events_per_journey=100,
            )

        async with database.session_factory() as session:
            work = (
                (
                    await session.execute(
                        select(journey_reduction_work).where(
                            journey_reduction_work.c.merchant_id == merchant_id,
                            journey_reduction_work.c.correlation_id == order_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            attempts = await session.scalar(
                select(func.count())
                .select_from(journey_reduction_attempts)
                .where(journey_reduction_attempts.c.merchant_id == merchant_id)
            )
        assert work["status"] == JourneyReductionStatus.PENDING.value
        assert work["attempt_count"] == 0
        assert attempts == 0
        assert await repository.get(merchant_id, order_id) is None
        await _drain_reductions(database)
    finally:
        await database.close()


async def test_repository_validates_inputs_and_replay_state() -> None:
    database = _database()
    repository = PostgresJourneyReductionRepository(database)
    try:
        with pytest.raises(ValueError, match="worker_id"):
            await repository.process_batch(
                reducer=TemporalPaymentJourneyReducer(),
                worker_id=" ",
                batch_size=1,
                max_events_per_journey=1,
            )
        with pytest.raises(ValueError, match="batch_size"):
            await repository.process_batch(
                reducer=TemporalPaymentJourneyReducer(),
                worker_id="worker",
                batch_size=0,
                max_events_per_journey=1,
            )
        with pytest.raises(ValueError, match="max_events_per_journey"):
            await repository.process_batch(
                reducer=TemporalPaymentJourneyReducer(),
                worker_id="worker",
                batch_size=1,
                max_events_per_journey=0,
            )
        with pytest.raises(JourneyReductionReplayNotAllowedError, match="completed"):
            await repository.request_replay(
                f"merchant-{uuid4()}",
                f"order-{uuid4()}",
                requested_by="operator",
                reason="Nothing exists.",
            )
        assert await repository.get(f"merchant-{uuid4()}", f"order-{uuid4()}") is None
    finally:
        await database.close()


async def test_temporal_audit_tables_reject_mutation() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    repository = PostgresJourneyReductionRepository(database)
    event = _raw_event(
        merchant_id=merchant_id,
        order_id=order_id,
        event_type="order.created",
        entity_id=order_id,
        status="created",
        minute=0,
    )
    try:
        await _drain_reductions(database)
        await _append_events(database, [event])
        await _drain_reductions(database)
        await repository.request_replay(
            merchant_id,
            order_id,
            requested_by="security-test",
            reason="Create immutable replay evidence.",
        )
        await _drain_reductions(database)

        statements = [
            "UPDATE ledger.payment_journey_revisions SET event_count = 2 "
            "WHERE merchant_id = :merchant_id",
            "DELETE FROM ledger.journey_reduction_attempts WHERE merchant_id = :merchant_id",
            "DELETE FROM ledger.journey_reduction_replays WHERE merchant_id = :merchant_id",
            "TRUNCATE ledger.payment_journey_revisions",
        ]
        for statement in statements:
            with pytest.raises(DBAPIError, match="append-only"):
                async with database.transaction() as session:
                    await session.execute(text(statement), {"merchant_id": merchant_id})
    finally:
        await database.close()
