"""Real PostgreSQL proofs for idempotency, concurrency, and immutability."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from chakravyuh.config import Settings
from chakravyuh.domain.enums import EventSource
from chakravyuh.domain.errors import EventIdentityConflictError
from chakravyuh.domain.webhooks import RawWebhookEvent
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.webhook_event_store import PostgresWebhookEventStore

TEST_POSTGRES_DSN = os.environ.get("CHAKRAVYUH_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(
    TEST_POSTGRES_DSN is None,
    reason="CHAKRAVYUH_TEST_POSTGRES_DSN is required for PostgreSQL integration proofs",
)


def _event(
    *, source_event_id: str, body: bytes = b'{"event":"payment.captured"}'
) -> RawWebhookEvent:
    now = datetime.now(UTC)
    return RawWebhookEvent(
        merchant_id=f"merchant-{uuid4()}",
        source=EventSource.RAZORPAY_WEBHOOK,
        source_event_id=source_event_id,
        event_type="payment.captured",
        account_id="acc_test",
        occurred_at=now,
        observed_at=now,
        payload={"event": "payment.captured"},
        raw_body=body,
    )


def _database() -> Database:
    assert TEST_POSTGRES_DSN is not None
    return Database(Settings(environment="test", postgres_dsn=TEST_POSTGRES_DSN))


async def test_postgres_ledger_is_idempotent_and_detects_identity_conflicts() -> None:
    database = _database()
    store = PostgresWebhookEventStore(database)
    original = _event(source_event_id=f"event-{uuid4()}")
    retry = original.model_copy(update={"event_id": uuid4()})
    conflict = original.model_copy(
        update={
            "event_id": uuid4(),
            "raw_body": b'{"event":"payment.failed"}',
            "payload": {"event": "payment.failed"},
        }
    )
    try:
        await database.ping()
        assert await store.append(original) is True
        assert await store.append(retry) is False
        stored = await store.get(original.merchant_id, original.source_event_id)
        assert stored == original
        with pytest.raises(EventIdentityConflictError):
            await store.append(conflict)
    finally:
        await database.close()


async def test_postgres_ledger_deduplicates_concurrent_delivery() -> None:
    database = _database()
    store = PostgresWebhookEventStore(database)
    first = _event(source_event_id=f"event-{uuid4()}")
    second = first.model_copy(update={"event_id": uuid4()})
    try:
        outcomes = await asyncio.gather(store.append(first), store.append(second))
        assert sorted(outcomes) == [False, True]
    finally:
        await database.close()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ledger.webhook_events SET event_type = 'changed' WHERE event_id = :event_id",
        "DELETE FROM ledger.webhook_events WHERE event_id = :event_id",
        "TRUNCATE ledger.webhook_events CASCADE",
    ],
)
async def test_postgres_ledger_rejects_mutation(statement: str) -> None:
    database = _database()
    store = PostgresWebhookEventStore(database)
    event = _event(source_event_id=f"event-{uuid4()}")
    try:
        assert await store.append(event) is True
        with pytest.raises(DBAPIError, match="append-only"):
            async with database.transaction() as session:
                await session.execute(text(statement), {"event_id": event.event_id})
    finally:
        await database.close()
