"""Atomic, append-only PostgreSQL webhook ledger."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping

from chakravyuh.domain.enums import EventSource
from chakravyuh.domain.errors import EventIdentityConflictError
from chakravyuh.domain.webhooks import RawWebhookEvent
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.tables import normalization_work, webhook_events


class PostgresWebhookEventStore:
    """Persist verified provider events exactly once per merchant identity."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def append(self, event: RawWebhookEvent) -> bool:
        values: dict[str, Any] = {
            "event_id": event.event_id,
            "merchant_id": event.merchant_id,
            "source": event.source.value,
            "source_event_id": event.source_event_id,
            "event_type": event.event_type,
            "account_id": event.account_id,
            "occurred_at": event.occurred_at,
            "observed_at": event.observed_at,
            "payload": event.payload,
            "raw_body": event.raw_body,
            "body_sha256": event.body_sha256,
        }
        statement = (
            insert(webhook_events)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["merchant_id", "source", "source_event_id"])
            .returning(webhook_events.c.event_id)
        )

        async with self._database.transaction() as session:
            inserted_id = (await session.execute(statement)).scalar_one_or_none()
            if inserted_id is not None:
                await session.execute(
                    insert(normalization_work)
                    .values(webhook_event_id=inserted_id)
                    .on_conflict_do_nothing(index_elements=["webhook_event_id"])
                )
                return True

            existing_hash = await session.scalar(
                select(webhook_events.c.body_sha256).where(
                    webhook_events.c.merchant_id == event.merchant_id,
                    webhook_events.c.source == event.source.value,
                    webhook_events.c.source_event_id == event.source_event_id,
                )
            )
            if existing_hash != event.body_sha256:
                msg = "provider event identity was reused with different content"
                raise EventIdentityConflictError(msg)
            return False

    async def get(
        self,
        merchant_id: str,
        source_event_id: str,
    ) -> RawWebhookEvent | None:
        statement = select(webhook_events).where(
            webhook_events.c.merchant_id == merchant_id,
            webhook_events.c.source == EventSource.RAZORPAY_WEBHOOK.value,
            webhook_events.c.source_event_id == source_event_id,
        )
        async with self._database.session_factory() as session:
            row = (await session.execute(statement)).mappings().one_or_none()
        return None if row is None else self._to_domain(row)

    @staticmethod
    def _to_domain(row: RowMapping) -> RawWebhookEvent:
        return RawWebhookEvent(
            event_id=row["event_id"],
            merchant_id=row["merchant_id"],
            source=EventSource(row["source"]),
            source_event_id=row["source_event_id"],
            event_type=row["event_type"],
            account_id=row["account_id"],
            occurred_at=row["occurred_at"],
            observed_at=row["observed_at"],
            payload=row["payload"],
            raw_body=bytes(row["raw_body"]),
        )
