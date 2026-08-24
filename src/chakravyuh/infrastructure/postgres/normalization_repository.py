"""PostgreSQL queue, normalized ledger, dead letters, and replay audit."""

from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from chakravyuh.application.normalization import NormalizationBatchResult
from chakravyuh.application.ports import WebhookNormalizer
from chakravyuh.domain.enums import EventSource, NormalizationOutcome, NormalizationStatus
from chakravyuh.domain.errors import NormalizationError, ReplayNotAllowedError
from chakravyuh.domain.events import NormalizedEvent
from chakravyuh.domain.webhooks import RawWebhookEvent
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.tables import (
    normalization_attempts,
    normalization_replays,
    normalization_work,
    normalized_events,
    webhook_events,
)


class PostgresNormalizationRepository:
    """Commit each claimed batch as one transaction with exactly-once effects."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def process_batch(
        self,
        *,
        normalizer: WebhookNormalizer,
        worker_id: str,
        batch_size: int,
    ) -> NormalizationBatchResult:
        worker_id = _bounded_text(worker_id, field="worker_id", maximum=255)
        if not 1 <= batch_size <= 500:
            msg = "batch_size must be between 1 and 500"
            raise ValueError(msg)

        completed = 0
        dead_lettered = 0
        async with self._database.transaction() as session:
            rows = (
                (
                    await session.execute(
                        select(webhook_events, normalization_work.c.attempt_count)
                        .select_from(
                            normalization_work.join(
                                webhook_events,
                                normalization_work.c.webhook_event_id == webhook_events.c.event_id,
                            )
                        )
                        .where(
                            normalization_work.c.status == NormalizationStatus.PENDING.value,
                            normalization_work.c.available_at <= func.now(),
                        )
                        .order_by(webhook_events.c.recorded_at, webhook_events.c.event_id)
                        .limit(batch_size)
                        .with_for_update(skip_locked=True, of=normalization_work)
                    )
                )
                .mappings()
                .all()
            )

            for row in rows:
                raw_event = _raw_event(row)
                attempt_number = int(row["attempt_count"]) + 1
                try:
                    normalized = normalizer.normalize(raw_event)
                except NormalizationError as failure:
                    await self._record_dead_letter(
                        session=session,
                        raw_event=raw_event,
                        attempt_number=attempt_number,
                        worker_id=worker_id,
                        normalizer_version=normalizer.version,
                        error_code=failure.code.value,
                    )
                    dead_lettered += 1
                else:
                    await self._record_completed(
                        session=session,
                        raw_event=raw_event,
                        normalized=normalized,
                        attempt_number=attempt_number,
                        worker_id=worker_id,
                        normalizer_version=normalizer.version,
                    )
                    completed += 1

        return NormalizationBatchResult(
            claimed=len(rows),
            completed=completed,
            dead_lettered=dead_lettered,
        )

    async def request_replay(
        self,
        event_id: UUID,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID:
        requested_by = _bounded_text(requested_by, field="requested_by", maximum=255)
        reason = _bounded_text(reason, field="reason", maximum=2_000)
        replay_id = uuid4()
        async with self._database.transaction() as session:
            queued_event_id = (
                await session.execute(
                    update(normalization_work)
                    .where(
                        normalization_work.c.webhook_event_id == event_id,
                        normalization_work.c.status == NormalizationStatus.DEAD_LETTER.value,
                    )
                    .values(
                        status=NormalizationStatus.PENDING.value,
                        available_at=func.now(),
                        last_error_code=None,
                        normalized_event_id=None,
                        updated_at=func.now(),
                    )
                    .returning(normalization_work.c.webhook_event_id)
                )
            ).scalar_one_or_none()
            if queued_event_id is None:
                msg = "only a dead-lettered event can be replayed"
                raise ReplayNotAllowedError(msg)

            await session.execute(
                insert(normalization_replays).values(
                    replay_id=replay_id,
                    webhook_event_id=event_id,
                    requested_by=requested_by,
                    reason=reason,
                )
            )
        return replay_id

    @staticmethod
    async def _record_completed(
        *,
        session: AsyncSession,
        raw_event: RawWebhookEvent,
        normalized: NormalizedEvent,
        attempt_number: int,
        worker_id: str,
        normalizer_version: str,
    ) -> None:
        await session.execute(
            insert(normalized_events).values(
                event_id=normalized.event_id,
                source_webhook_event_id=raw_event.event_id,
                schema_version=normalized.schema_version,
                merchant_id=normalized.merchant_id,
                source=normalized.source.value,
                source_event_id=normalized.source_event_id,
                event_type=normalized.event_type,
                subject_type=normalized.subject.entity_type.value,
                subject_id=normalized.subject.entity_id,
                occurred_at=normalized.occurred_at,
                observed_at=normalized.observed_at,
                correlation_id=normalized.correlation_id,
                payload=normalized.payload,
                normalizer_version=normalizer_version,
            )
        )
        await session.execute(
            insert(normalization_attempts).values(
                attempt_id=uuid4(),
                webhook_event_id=raw_event.event_id,
                attempt_number=attempt_number,
                worker_id=worker_id,
                outcome=NormalizationOutcome.COMPLETED.value,
                error_code=None,
                normalized_event_id=normalized.event_id,
                normalizer_version=normalizer_version,
            )
        )
        await session.execute(
            update(normalization_work)
            .where(normalization_work.c.webhook_event_id == raw_event.event_id)
            .values(
                status=NormalizationStatus.COMPLETED.value,
                attempt_count=attempt_number,
                last_error_code=None,
                normalized_event_id=normalized.event_id,
                updated_at=func.now(),
            )
        )

    @staticmethod
    async def _record_dead_letter(
        *,
        session: AsyncSession,
        raw_event: RawWebhookEvent,
        attempt_number: int,
        worker_id: str,
        normalizer_version: str,
        error_code: str,
    ) -> None:
        await session.execute(
            insert(normalization_attempts).values(
                attempt_id=uuid4(),
                webhook_event_id=raw_event.event_id,
                attempt_number=attempt_number,
                worker_id=worker_id,
                outcome=NormalizationOutcome.DEAD_LETTER.value,
                error_code=error_code,
                normalized_event_id=None,
                normalizer_version=normalizer_version,
            )
        )
        await session.execute(
            update(normalization_work)
            .where(normalization_work.c.webhook_event_id == raw_event.event_id)
            .values(
                status=NormalizationStatus.DEAD_LETTER.value,
                attempt_count=attempt_number,
                last_error_code=error_code,
                normalized_event_id=None,
                updated_at=func.now(),
            )
        )


def _raw_event(row: RowMapping) -> RawWebhookEvent:
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


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    value = value.strip()
    if not value or len(value) > maximum:
        msg = f"{field} must contain between 1 and {maximum} characters"
        raise ValueError(msg)
    return value
