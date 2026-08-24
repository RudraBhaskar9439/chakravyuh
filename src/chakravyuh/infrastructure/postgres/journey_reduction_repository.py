"""PostgreSQL temporal journey queue, states, revisions, and replay audit."""

from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from chakravyuh.application.journey_reduction import JourneyReductionBatchResult
from chakravyuh.application.ports import JourneyReducer
from chakravyuh.domain.enums import (
    EntityType,
    EventSource,
    JourneyReductionOutcome,
    JourneyReductionStatus,
)
from chakravyuh.domain.errors import (
    JourneyReductionError,
    JourneyReductionErrorCode,
    JourneyReductionReplayNotAllowedError,
)
from chakravyuh.domain.events import EntityReference, NormalizedEvent
from chakravyuh.domain.journeys import PaymentJourneyState, journey_state_hash
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.tables import (
    journey_reduction_attempts,
    journey_reduction_replays,
    journey_reduction_work,
    normalized_events,
    payment_journey_revisions,
    payment_journey_states,
)


class PostgresJourneyReductionRepository:
    """Rebuild complete correlations under a queue-row transaction lock."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def process_batch(
        self,
        *,
        reducer: JourneyReducer,
        worker_id: str,
        batch_size: int,
        max_events_per_journey: int,
    ) -> JourneyReductionBatchResult:
        worker_id = _bounded_text(worker_id, field="worker_id", maximum=255)
        if not 1 <= batch_size <= 500:
            msg = "batch_size must be between 1 and 500"
            raise ValueError(msg)
        if not 1 <= max_events_per_journey <= 100_000:
            msg = "max_events_per_journey must be between 1 and 100000"
            raise ValueError(msg)

        completed = 0
        dead_lettered = 0
        async with self._database.transaction() as session:
            work_rows = (
                (
                    await session.execute(
                        select(journey_reduction_work)
                        .where(
                            journey_reduction_work.c.status == JourneyReductionStatus.PENDING.value,
                            journey_reduction_work.c.available_at <= func.now(),
                        )
                        .order_by(
                            journey_reduction_work.c.updated_at,
                            journey_reduction_work.c.merchant_id,
                            journey_reduction_work.c.correlation_id,
                        )
                        .limit(batch_size)
                        .with_for_update(skip_locked=True, of=journey_reduction_work)
                    )
                )
                .mappings()
                .all()
            )
            for work in work_rows:
                events = await _load_events(
                    session,
                    merchant_id=work["merchant_id"],
                    correlation_id=work["correlation_id"],
                    limit=max_events_per_journey + 1,
                )
                attempt_number = int(work["attempt_count"]) + 1
                generation = int(work["generation"])
                try:
                    if len(events) > max_events_per_journey:
                        raise JourneyReductionError(JourneyReductionErrorCode.JOURNEY_TOO_LARGE)
                    state = reducer.reduce(events)
                except JourneyReductionError as failure:
                    await _record_dead_letter(
                        session,
                        merchant_id=work["merchant_id"],
                        correlation_id=work["correlation_id"],
                        generation=generation,
                        attempt_number=attempt_number,
                        worker_id=worker_id,
                        reducer_version=reducer.version,
                        error_code=failure.code.value,
                    )
                    dead_lettered += 1
                else:
                    await _record_completed(
                        session,
                        state=state,
                        generation=generation,
                        attempt_number=attempt_number,
                        worker_id=worker_id,
                        reducer_version=reducer.version,
                    )
                    completed += 1

        return JourneyReductionBatchResult(
            claimed=len(work_rows),
            completed=completed,
            dead_lettered=dead_lettered,
        )

    async def request_replay(
        self,
        merchant_id: str,
        correlation_id: str,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID:
        merchant_id = _bounded_text(merchant_id, field="merchant_id", maximum=255)
        correlation_id = _bounded_text(correlation_id, field="correlation_id", maximum=255)
        requested_by = _bounded_text(requested_by, field="requested_by", maximum=255)
        reason = _bounded_text(reason, field="reason", maximum=2_000)
        replay_id = uuid4()
        async with self._database.transaction() as session:
            row = (
                (
                    await session.execute(
                        select(journey_reduction_work)
                        .where(
                            journey_reduction_work.c.merchant_id == merchant_id,
                            journey_reduction_work.c.correlation_id == correlation_id,
                            journey_reduction_work.c.status.in_(
                                [
                                    JourneyReductionStatus.COMPLETED.value,
                                    JourneyReductionStatus.DEAD_LETTER.value,
                                ]
                            ),
                        )
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                msg = "only a completed or dead-lettered journey can be replayed"
                raise JourneyReductionReplayNotAllowedError(msg)
            generation = int(row["generation"])
            if row["status"] == JourneyReductionStatus.COMPLETED.value:
                generation += 1
            await session.execute(
                update(journey_reduction_work)
                .where(
                    journey_reduction_work.c.merchant_id == merchant_id,
                    journey_reduction_work.c.correlation_id == correlation_id,
                )
                .values(
                    generation=generation,
                    status=JourneyReductionStatus.PENDING.value,
                    available_at=func.now(),
                    last_error_code=None,
                    updated_at=func.now(),
                )
            )
            await session.execute(
                insert(journey_reduction_replays).values(
                    replay_id=replay_id,
                    merchant_id=merchant_id,
                    correlation_id=correlation_id,
                    generation=generation,
                    requested_by=requested_by,
                    reason=reason,
                )
            )
        return replay_id

    async def get(
        self,
        merchant_id: str,
        correlation_id: str,
    ) -> PaymentJourneyState | None:
        merchant_id = _bounded_text(merchant_id, field="merchant_id", maximum=255)
        correlation_id = _bounded_text(correlation_id, field="correlation_id", maximum=255)
        async with self._database.session_factory() as session:
            state = await session.scalar(
                select(payment_journey_states.c.state).where(
                    payment_journey_states.c.merchant_id == merchant_id,
                    payment_journey_states.c.correlation_id == correlation_id,
                )
            )
        return None if state is None else PaymentJourneyState.model_validate(state)


async def _load_events(
    session: AsyncSession,
    *,
    merchant_id: str,
    correlation_id: str,
    limit: int,
) -> list[NormalizedEvent]:
    rows = (
        (
            await session.execute(
                select(normalized_events)
                .where(
                    normalized_events.c.merchant_id == merchant_id,
                    normalized_events.c.correlation_id == correlation_id,
                )
                .order_by(
                    normalized_events.c.occurred_at,
                    normalized_events.c.observed_at,
                    normalized_events.c.event_type,
                    normalized_events.c.source_event_id,
                    normalized_events.c.event_id,
                )
                .limit(limit)
            )
        )
        .mappings()
        .all()
    )
    return [_normalized_event(row) for row in rows]


async def _record_completed(
    session: AsyncSession,
    *,
    state: PaymentJourneyState,
    generation: int,
    attempt_number: int,
    worker_id: str,
    reducer_version: str,
) -> None:
    state_hash = journey_state_hash(state)
    state_json = state.model_dump(mode="json")
    revision_id = uuid5(
        NAMESPACE_URL,
        "chakravyuh:journey-revision:"
        f"{state.merchant_id}:{state.correlation_id}:{generation}:{state_hash}",
    )
    await session.execute(
        insert(payment_journey_states)
        .values(
            merchant_id=state.merchant_id,
            correlation_id=state.correlation_id,
            generation=generation,
            event_count=state.event_count,
            reducer_version=reducer_version,
            state_hash=state_hash,
            last_occurred_at=state.last_occurred_at,
            state=state_json,
        )
        .on_conflict_do_update(
            index_elements=["merchant_id", "correlation_id"],
            set_={
                "generation": generation,
                "event_count": state.event_count,
                "reducer_version": reducer_version,
                "state_hash": state_hash,
                "last_occurred_at": state.last_occurred_at,
                "state": state_json,
                "updated_at": func.now(),
            },
        )
    )
    await session.execute(
        insert(payment_journey_revisions).values(
            revision_id=revision_id,
            merchant_id=state.merchant_id,
            correlation_id=state.correlation_id,
            generation=generation,
            event_count=state.event_count,
            reducer_version=reducer_version,
            state_hash=state_hash,
            state=state_json,
        )
    )
    await session.execute(
        insert(journey_reduction_attempts).values(
            attempt_id=uuid4(),
            merchant_id=state.merchant_id,
            correlation_id=state.correlation_id,
            generation=generation,
            attempt_number=attempt_number,
            worker_id=worker_id,
            reducer_version=reducer_version,
            outcome=JourneyReductionOutcome.COMPLETED.value,
            error_code=None,
            state_hash=state_hash,
        )
    )
    await session.execute(
        update(journey_reduction_work)
        .where(
            journey_reduction_work.c.merchant_id == state.merchant_id,
            journey_reduction_work.c.correlation_id == state.correlation_id,
        )
        .values(
            applied_generation=generation,
            status=JourneyReductionStatus.COMPLETED.value,
            attempt_count=attempt_number,
            last_error_code=None,
            updated_at=func.now(),
        )
    )


async def _record_dead_letter(
    session: AsyncSession,
    *,
    merchant_id: str,
    correlation_id: str,
    generation: int,
    attempt_number: int,
    worker_id: str,
    reducer_version: str,
    error_code: str,
) -> None:
    await session.execute(
        insert(journey_reduction_attempts).values(
            attempt_id=uuid4(),
            merchant_id=merchant_id,
            correlation_id=correlation_id,
            generation=generation,
            attempt_number=attempt_number,
            worker_id=worker_id,
            reducer_version=reducer_version,
            outcome=JourneyReductionOutcome.DEAD_LETTER.value,
            error_code=error_code,
            state_hash=None,
        )
    )
    await session.execute(
        update(journey_reduction_work)
        .where(
            journey_reduction_work.c.merchant_id == merchant_id,
            journey_reduction_work.c.correlation_id == correlation_id,
        )
        .values(
            status=JourneyReductionStatus.DEAD_LETTER.value,
            attempt_count=attempt_number,
            last_error_code=error_code,
            updated_at=func.now(),
        )
    )


def _normalized_event(row: RowMapping) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=row["event_id"],
        schema_version=row["schema_version"],
        merchant_id=row["merchant_id"],
        source=EventSource(row["source"]),
        source_event_id=row["source_event_id"],
        event_type=row["event_type"],
        subject=EntityReference(
            entity_type=EntityType(row["subject_type"]),
            entity_id=row["subject_id"],
        ),
        occurred_at=row["occurred_at"],
        observed_at=row["observed_at"],
        correlation_id=row["correlation_id"],
        payload=row["payload"],
    )


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    value = value.strip()
    if not value or len(value) > maximum:
        msg = f"{field} must contain between 1 and {maximum} characters"
        raise ValueError(msg)
    return value
