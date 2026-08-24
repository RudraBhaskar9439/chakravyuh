"""Real PostgreSQL proofs for durable normalization and audited replay."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from chakravyuh.config import Settings
from chakravyuh.domain.enums import EventSource, NormalizationStatus
from chakravyuh.domain.errors import ReplayNotAllowedError
from chakravyuh.domain.events import NormalizedEvent
from chakravyuh.domain.webhooks import RawWebhookEvent
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.normalization_repository import (
    PostgresNormalizationRepository,
)
from chakravyuh.infrastructure.postgres.tables import (
    normalization_attempts,
    normalization_replays,
    normalization_work,
    normalized_events,
)
from chakravyuh.infrastructure.postgres.webhook_event_store import PostgresWebhookEventStore
from chakravyuh.infrastructure.razorpay.normalizer import RazorpayWebhookNormalizer

TEST_POSTGRES_DSN = os.environ.get("CHAKRAVYUH_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(
    TEST_POSTGRES_DSN is None,
    reason="CHAKRAVYUH_TEST_POSTGRES_DSN is required for PostgreSQL integration proofs",
)


class ExplodingNormalizer:
    version = "exploding-test-v1"

    def normalize(self, event: RawWebhookEvent) -> NormalizedEvent:
        raise RuntimeError("simulated process failure")


def _database() -> Database:
    assert TEST_POSTGRES_DSN is not None
    return Database(Settings(environment="test", postgres_dsn=TEST_POSTGRES_DSN))


def _event(event_type: str = "payment.captured") -> RawWebhookEvent:
    now = datetime.now(UTC)
    family = event_type.partition(".")[0]
    entity_id = {
        "order": "order",
        "payment": "pay",
        "payment_link": "plink",
        "refund": "rfnd",
    }.get(family, "unsupported")
    payload = {
        "event": event_type,
        "payload": {family: {"entity": {"id": f"{entity_id}_{uuid4()}"}}},
    }
    return RawWebhookEvent(
        merchant_id=f"merchant-{uuid4()}",
        source=EventSource.RAZORPAY_WEBHOOK,
        source_event_id=f"event-{uuid4()}",
        event_type=event_type,
        account_id="acc_test",
        occurred_at=now,
        observed_at=now,
        payload=payload,
        raw_body=b'{"verified":true}',
    )


async def _drain(repository: PostgresNormalizationRepository) -> None:
    normalizer = RazorpayWebhookNormalizer()
    while True:
        result = await repository.process_batch(
            normalizer=normalizer,
            worker_id="integration-drain",
            batch_size=500,
        )
        if result.claimed == 0:
            return


async def test_ingestion_enqueues_and_worker_commits_exactly_once_output() -> None:
    database = _database()
    raw_store = PostgresWebhookEventStore(database)
    repository = PostgresNormalizationRepository(database)
    event = _event()
    try:
        await _drain(repository)
        assert await raw_store.append(event) is True

        result = await repository.process_batch(
            normalizer=RazorpayWebhookNormalizer(),
            worker_id="worker-one",
            batch_size=10,
        )

        assert result.completed == 1
        async with database.session_factory() as session:
            work = (
                (
                    await session.execute(
                        select(normalization_work).where(
                            normalization_work.c.webhook_event_id == event.event_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            normalized = (
                (
                    await session.execute(
                        select(normalized_events).where(
                            normalized_events.c.source_webhook_event_id == event.event_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            attempt_count = await session.scalar(
                select(func.count())
                .select_from(normalization_attempts)
                .where(normalization_attempts.c.webhook_event_id == event.event_id)
            )
        assert work["status"] == NormalizationStatus.COMPLETED.value
        assert work["attempt_count"] == 1
        assert normalized["event_type"] == event.event_type
        assert normalized["normalizer_version"] == RazorpayWebhookNormalizer.version
        assert attempt_count == 1
        with pytest.raises(ReplayNotAllowedError, match="dead-lettered"):
            await repository.request_replay(
                event.event_id,
                requested_by="operator",
                reason="Completed events must not be replayed.",
            )
    finally:
        await database.close()


async def test_repository_rejects_unbounded_operational_inputs() -> None:
    database = _database()
    repository = PostgresNormalizationRepository(database)
    try:
        with pytest.raises(ValueError, match="worker_id"):
            await repository.process_batch(
                normalizer=RazorpayWebhookNormalizer(),
                worker_id=" ",
                batch_size=1,
            )
        with pytest.raises(ValueError, match="batch_size"):
            await repository.process_batch(
                normalizer=RazorpayWebhookNormalizer(),
                worker_id="worker",
                batch_size=0,
            )
        with pytest.raises(ValueError, match="reason"):
            await repository.request_replay(
                uuid4(),
                requested_by="operator",
                reason=" ",
            )
    finally:
        await database.close()


async def test_concurrent_workers_do_not_duplicate_outputs() -> None:
    database = _database()
    raw_store = PostgresWebhookEventStore(database)
    repository = PostgresNormalizationRepository(database)
    events = [_event() for _ in range(8)]
    try:
        await _drain(repository)
        for event in events:
            assert await raw_store.append(event) is True

        results = await asyncio.gather(
            *(
                repository.process_batch(
                    normalizer=RazorpayWebhookNormalizer(),
                    worker_id=f"worker-{worker_number}",
                    batch_size=2,
                )
                for worker_number in range(4)
            )
        )

        assert sum(result.claimed for result in results) == len(events)
        async with database.session_factory() as session:
            output_count = await session.scalar(
                select(func.count())
                .select_from(normalized_events)
                .where(
                    normalized_events.c.source_webhook_event_id.in_(
                        [event.event_id for event in events]
                    )
                )
            )
            attempt_count = await session.scalar(
                select(func.count())
                .select_from(normalization_attempts)
                .where(
                    normalization_attempts.c.webhook_event_id.in_(
                        [event.event_id for event in events]
                    )
                )
            )
        assert output_count == len(events)
        assert attempt_count == len(events)
    finally:
        await database.close()


async def test_dead_letter_replay_is_audited_and_reprocesses() -> None:
    database = _database()
    raw_store = PostgresWebhookEventStore(database)
    repository = PostgresNormalizationRepository(database)
    event = _event("subscription.charged")
    try:
        await _drain(repository)
        assert await raw_store.append(event) is True
        first = await repository.process_batch(
            normalizer=RazorpayWebhookNormalizer(),
            worker_id="worker-dlq",
            batch_size=1,
        )
        assert first.dead_lettered == 1

        replay_id = await repository.request_replay(
            event.event_id,
            requested_by="operator@example.test",
            reason="Normalizer release now supports this provider contract.",
        )
        second = await repository.process_batch(
            normalizer=RazorpayWebhookNormalizer(),
            worker_id="worker-dlq",
            batch_size=1,
        )

        assert second.dead_lettered == 1
        async with database.session_factory() as session:
            work = (
                (
                    await session.execute(
                        select(normalization_work).where(
                            normalization_work.c.webhook_event_id == event.event_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            attempts = await session.scalar(
                select(func.count())
                .select_from(normalization_attempts)
                .where(normalization_attempts.c.webhook_event_id == event.event_id)
            )
            replay = (
                (
                    await session.execute(
                        select(normalization_replays).where(
                            normalization_replays.c.replay_id == replay_id
                        )
                    )
                )
                .mappings()
                .one()
            )
        assert work["status"] == NormalizationStatus.DEAD_LETTER.value
        assert work["attempt_count"] == 2
        assert attempts == 2
        assert replay["requested_by"] == "operator@example.test"
    finally:
        await database.close()


async def test_unexpected_failure_rolls_claim_back_to_pending() -> None:
    database = _database()
    raw_store = PostgresWebhookEventStore(database)
    repository = PostgresNormalizationRepository(database)
    event = _event()
    try:
        await _drain(repository)
        assert await raw_store.append(event) is True

        with pytest.raises(RuntimeError, match="simulated process failure"):
            await repository.process_batch(
                normalizer=ExplodingNormalizer(),
                worker_id="worker-crash",
                batch_size=1,
            )

        async with database.session_factory() as session:
            work = (
                (
                    await session.execute(
                        select(normalization_work).where(
                            normalization_work.c.webhook_event_id == event.event_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            outputs = await session.scalar(
                select(func.count())
                .select_from(normalized_events)
                .where(normalized_events.c.source_webhook_event_id == event.event_id)
            )
            attempts = await session.scalar(
                select(func.count())
                .select_from(normalization_attempts)
                .where(normalization_attempts.c.webhook_event_id == event.event_id)
            )
        assert work["status"] == NormalizationStatus.PENDING.value
        assert work["attempt_count"] == 0
        assert outputs == 0
        assert attempts == 0
    finally:
        await database.close()


async def test_normalization_audit_tables_reject_mutation() -> None:
    database = _database()
    raw_store = PostgresWebhookEventStore(database)
    repository = PostgresNormalizationRepository(database)
    valid = _event()
    invalid = _event("subscription.charged")
    try:
        await _drain(repository)
        assert await raw_store.append(valid) is True
        assert await raw_store.append(invalid) is True
        await _drain(repository)
        await repository.request_replay(
            invalid.event_id,
            requested_by="security-test",
            reason="Prove replay audit immutability.",
        )

        statements = [
            (
                "UPDATE ledger.normalized_events SET event_type = 'changed' "
                "WHERE source_webhook_event_id = :event_id",
                valid.event_id,
            ),
            (
                "DELETE FROM ledger.normalization_attempts WHERE webhook_event_id = :event_id",
                valid.event_id,
            ),
            (
                "DELETE FROM ledger.normalization_replays WHERE webhook_event_id = :event_id",
                invalid.event_id,
            ),
            ("TRUNCATE ledger.normalized_events CASCADE", valid.event_id),
        ]
        for statement, event_id in statements:
            with pytest.raises(DBAPIError, match="append-only"):
                async with database.transaction() as session:
                    await session.execute(text(statement), {"event_id": event_id})
    finally:
        await database.close()
