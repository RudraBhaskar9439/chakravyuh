"""PostgreSQL leases, checkpoints, lag, attempts, and rebuild audit for Neo4j."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import case, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from chakravyuh.domain.enums import (
    EntityType,
    EventSource,
    GraphProjectionOutcome,
    GraphProjectionStatus,
)
from chakravyuh.domain.errors import GraphRebuildNotAllowedError, ProjectionLeaseLostError
from chakravyuh.domain.events import EntityReference, NormalizedEvent
from chakravyuh.domain.journeys import PaymentJourneyState
from chakravyuh.domain.projections import (
    GraphProjectionInput,
    GraphProjectionReceipt,
    GraphRebuildCandidate,
    GraphRebuildReceipt,
    ProjectionLag,
    ProjectionWorkClaim,
)
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.tables import (
    graph_projection_attempts,
    graph_projection_rebuild_completions,
    graph_projection_rebuilds,
    graph_projection_work,
    normalized_events,
    payment_journey_states,
)


class PostgresGraphProjectionRepository:
    """Coordinate an at-least-once graph projection without a distributed transaction."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def claim_batch(
        self,
        *,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
    ) -> list[ProjectionWorkClaim]:
        worker_id = _bounded_text(worker_id, field="worker_id", maximum=255)
        if not 1 <= batch_size <= 500:
            msg = "batch_size must be between 1 and 500"
            raise ValueError(msg)
        if not 1 <= lease_seconds <= 3_600:
            msg = "lease_seconds must be between 1 and 3600"
            raise ValueError(msg)

        claims: list[ProjectionWorkClaim] = []
        async with self._database.transaction() as session:
            database_now = await session.scalar(select(func.now()))
            assert database_now is not None
            lease_expires_at = database_now + timedelta(seconds=lease_seconds)
            rows = (
                (
                    await session.execute(
                        select(graph_projection_work)
                        .where(
                            or_(
                                (
                                    graph_projection_work.c.status
                                    == GraphProjectionStatus.PENDING.value
                                )
                                & (graph_projection_work.c.available_at <= database_now),
                                (
                                    graph_projection_work.c.status
                                    == GraphProjectionStatus.PROCESSING.value
                                )
                                & (graph_projection_work.c.lease_expires_at <= database_now),
                            )
                        )
                        .order_by(
                            graph_projection_work.c.desired_at,
                            graph_projection_work.c.merchant_id,
                            graph_projection_work.c.correlation_id,
                        )
                        .limit(batch_size)
                        .with_for_update(skip_locked=True, of=graph_projection_work)
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                attempt_number = int(row["attempt_count"]) + 1
                await session.execute(
                    update(graph_projection_work)
                    .where(
                        graph_projection_work.c.merchant_id == row["merchant_id"],
                        graph_projection_work.c.correlation_id == row["correlation_id"],
                    )
                    .values(
                        status=GraphProjectionStatus.PROCESSING.value,
                        attempt_count=attempt_number,
                        lease_owner=worker_id,
                        lease_expires_at=lease_expires_at,
                        updated_at=func.now(),
                    )
                )
                claims.append(
                    ProjectionWorkClaim(
                        merchant_id=row["merchant_id"],
                        correlation_id=row["correlation_id"],
                        target_version=row["target_version"],
                        state_generation=row["state_generation"],
                        projection_epoch=row["projection_epoch"],
                        attempt_number=attempt_number,
                        lease_owner=worker_id,
                        leased_until=lease_expires_at,
                    )
                )
        return claims

    async def load(self, claim: ProjectionWorkClaim) -> GraphProjectionInput:
        async with self._database.session_factory() as session:
            state_row = (
                (
                    await session.execute(
                        select(payment_journey_states).where(
                            payment_journey_states.c.merchant_id == claim.merchant_id,
                            payment_journey_states.c.correlation_id == claim.correlation_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if state_row is None:
                msg = "authoritative journey state disappeared during projection"
                raise ProjectionLeaseLostError(msg)
            event_rows = (
                (
                    await session.execute(
                        select(normalized_events)
                        .where(
                            normalized_events.c.merchant_id == claim.merchant_id,
                            normalized_events.c.correlation_id == claim.correlation_id,
                        )
                        .order_by(
                            normalized_events.c.occurred_at,
                            normalized_events.c.observed_at,
                            normalized_events.c.event_type,
                            normalized_events.c.source_event_id,
                            normalized_events.c.event_id,
                        )
                    )
                )
                .mappings()
                .all()
            )
        return GraphProjectionInput(
            state_generation=state_row["generation"],
            projection_epoch=claim.projection_epoch,
            state_hash=state_row["state_hash"],
            state=PaymentJourneyState.model_validate(state_row["state"]),
            events=tuple(_normalized_event(row) for row in event_rows),
        )

    async def complete(
        self,
        claim: ProjectionWorkClaim,
        receipt: GraphProjectionReceipt,
    ) -> None:
        _validate_receipt(claim, receipt)
        async with self._database.transaction() as session:
            row = await _locked_lease(session, claim)
            target_version = int(row["target_version"])
            status = (
                GraphProjectionStatus.COMPLETED.value
                if target_version == claim.target_version
                else GraphProjectionStatus.PENDING.value
            )
            await session.execute(
                insert(graph_projection_attempts).values(
                    attempt_id=uuid4(),
                    merchant_id=claim.merchant_id,
                    correlation_id=claim.correlation_id,
                    target_version=claim.target_version,
                    state_generation=receipt.state_generation,
                    projection_epoch=receipt.projection_epoch,
                    attempt_number=claim.attempt_number,
                    worker_id=claim.lease_owner,
                    outcome=GraphProjectionOutcome.COMPLETED.value,
                    error_code=None,
                    state_hash=receipt.state_hash,
                )
            )
            await session.execute(
                update(graph_projection_work)
                .where(
                    graph_projection_work.c.merchant_id == claim.merchant_id,
                    graph_projection_work.c.correlation_id == claim.correlation_id,
                )
                .values(
                    applied_version=claim.target_version,
                    projected_state_generation=receipt.state_generation,
                    status=status,
                    failure_count=0,
                    available_at=func.now(),
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code=None,
                    updated_at=func.now(),
                )
            )

    async def fail(
        self,
        claim: ProjectionWorkClaim,
        *,
        error_code: str,
        max_failures: int,
        retry_delay_seconds: float,
    ) -> bool:
        error_code = _bounded_text(error_code, field="error_code", maximum=64)
        if not 1 <= max_failures <= 100:
            msg = "max_failures must be between 1 and 100"
            raise ValueError(msg)
        if not 0 <= retry_delay_seconds <= 3_600:
            msg = "retry_delay_seconds must be between 0 and 3600"
            raise ValueError(msg)

        async with self._database.transaction() as session:
            row = await _locked_lease(session, claim)
            stale_claim = int(row["target_version"]) != claim.target_version
            failure_count = 0 if stale_claim else int(row["failure_count"]) + 1
            dead_lettered = not stale_claim and failure_count >= max_failures
            outcome = (
                GraphProjectionOutcome.DEAD_LETTER.value
                if dead_lettered
                else GraphProjectionOutcome.RETRY.value
            )
            await session.execute(
                insert(graph_projection_attempts).values(
                    attempt_id=uuid4(),
                    merchant_id=claim.merchant_id,
                    correlation_id=claim.correlation_id,
                    target_version=claim.target_version,
                    state_generation=claim.state_generation,
                    projection_epoch=claim.projection_epoch,
                    attempt_number=claim.attempt_number,
                    worker_id=claim.lease_owner,
                    outcome=outcome,
                    error_code=error_code,
                    state_hash=None,
                )
            )
            retry_at = func.now() + timedelta(seconds=retry_delay_seconds)
            await session.execute(
                update(graph_projection_work)
                .where(
                    graph_projection_work.c.merchant_id == claim.merchant_id,
                    graph_projection_work.c.correlation_id == claim.correlation_id,
                )
                .values(
                    status=(
                        GraphProjectionStatus.DEAD_LETTER.value
                        if dead_lettered
                        else GraphProjectionStatus.PENDING.value
                    ),
                    failure_count=failure_count,
                    available_at=retry_at,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code=error_code,
                    updated_at=func.now(),
                )
            )
        return dead_lettered

    async def lag(self) -> ProjectionLag:
        unprojected = graph_projection_work.c.status != GraphProjectionStatus.COMPLETED.value
        async with self._database.session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(
                            func.count()
                            .filter(
                                graph_projection_work.c.status
                                == GraphProjectionStatus.PENDING.value
                            )
                            .label("pending_count"),
                            func.count()
                            .filter(
                                graph_projection_work.c.status
                                == GraphProjectionStatus.PROCESSING.value
                            )
                            .label("processing_count"),
                            func.count()
                            .filter(
                                graph_projection_work.c.status
                                == GraphProjectionStatus.DEAD_LETTER.value
                            )
                            .label("dead_letter_count"),
                            func.coalesce(
                                func.max(
                                    graph_projection_work.c.target_version
                                    - graph_projection_work.c.applied_version
                                ).filter(unprojected),
                                0,
                            ).label("max_version_lag"),
                            func.min(graph_projection_work.c.desired_at)
                            .filter(unprojected)
                            .label("oldest_unprojected_at"),
                            func.coalesce(
                                func.extract(
                                    "epoch",
                                    func.now()
                                    - func.min(graph_projection_work.c.desired_at).filter(
                                        unprojected
                                    ),
                                ),
                                0,
                            ).label("oldest_age"),
                            select(func.count())
                            .select_from(graph_projection_rebuilds)
                            .where(
                                ~exists().where(
                                    graph_projection_rebuild_completions.c.rebuild_id
                                    == graph_projection_rebuilds.c.rebuild_id
                                )
                            )
                            .scalar_subquery()
                            .label("pending_rebuild_count"),
                        )
                    )
                )
                .mappings()
                .one()
            )
        return ProjectionLag(
            pending_count=row["pending_count"],
            processing_count=row["processing_count"],
            dead_letter_count=row["dead_letter_count"],
            pending_rebuild_count=row["pending_rebuild_count"],
            max_version_lag=row["max_version_lag"],
            oldest_unprojected_at=row["oldest_unprojected_at"],
            oldest_unprojected_age_seconds=float(row["oldest_age"]),
        )

    async def request_rebuild(
        self,
        *,
        requested_by: str,
        reason: str,
    ) -> tuple[UUID, int]:
        requested_by = _bounded_text(requested_by, field="requested_by", maximum=255)
        reason = _bounded_text(reason, field="reason", maximum=2_000)
        rebuild_id = uuid4()
        async with self._database.transaction() as session:
            journey_count = int(
                await session.scalar(select(func.count()).select_from(payment_journey_states)) or 0
            )
            if journey_count == 0:
                msg = "no authoritative journey states exist to rebuild"
                raise GraphRebuildNotAllowedError(msg)
            await session.execute(
                update(graph_projection_work).values(
                    target_version=graph_projection_work.c.target_version + 1,
                    projection_epoch=func.now(),
                    status=case(
                        (
                            graph_projection_work.c.status
                            == GraphProjectionStatus.PROCESSING.value,
                            GraphProjectionStatus.PROCESSING.value,
                        ),
                        else_=GraphProjectionStatus.PENDING.value,
                    ),
                    failure_count=0,
                    desired_at=func.now(),
                    available_at=func.now(),
                    last_error_code=None,
                    updated_at=func.now(),
                )
            )
            await session.execute(
                insert(graph_projection_rebuilds).values(
                    rebuild_id=rebuild_id,
                    requested_by=requested_by,
                    reason=reason,
                    journey_count=journey_count,
                    projection_epoch=func.now(),
                )
            )
        return rebuild_id, journey_count

    async def finalizable_rebuilds(self, *, limit: int) -> list[GraphRebuildCandidate]:
        if not 1 <= limit <= 100:
            msg = "limit must be between 1 and 100"
            raise ValueError(msg)
        unfinished_work = exists().where(
            graph_projection_work.c.projection_epoch
            <= graph_projection_rebuilds.c.projection_epoch,
            graph_projection_work.c.status != GraphProjectionStatus.COMPLETED.value,
        )
        already_completed = exists().where(
            graph_projection_rebuild_completions.c.rebuild_id
            == graph_projection_rebuilds.c.rebuild_id
        )
        async with self._database.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(
                            graph_projection_rebuilds.c.rebuild_id,
                            graph_projection_rebuilds.c.projection_epoch,
                        )
                        .where(~already_completed, ~unfinished_work)
                        .order_by(graph_projection_rebuilds.c.projection_epoch)
                        .limit(limit)
                    )
                )
                .mappings()
                .all()
            )
        return [GraphRebuildCandidate.model_validate(row) for row in rows]

    async def complete_rebuild(
        self,
        rebuild: GraphRebuildCandidate,
        receipt: GraphRebuildReceipt,
    ) -> bool:
        if (
            receipt.rebuild_id != rebuild.rebuild_id
            or receipt.projection_epoch != rebuild.projection_epoch
        ):
            msg = "graph rebuild receipt does not match its candidate"
            raise ValueError(msg)
        completion_id = uuid4()
        async with self._database.transaction() as session:
            inserted = await session.scalar(
                insert(graph_projection_rebuild_completions)
                .values(
                    completion_id=completion_id,
                    rebuild_id=rebuild.rebuild_id,
                    projection_epoch=rebuild.projection_epoch,
                    journey_count_removed=receipt.journey_count_removed,
                    entity_count_removed=receipt.entity_count_removed,
                    event_count_removed=receipt.event_count_removed,
                    merchant_count_removed=receipt.merchant_count_removed,
                )
                .on_conflict_do_nothing(
                    index_elements=[graph_projection_rebuild_completions.c.rebuild_id]
                )
                .returning(graph_projection_rebuild_completions.c.completion_id)
            )
        return inserted == completion_id


async def _locked_lease(
    session: AsyncSession,
    claim: ProjectionWorkClaim,
) -> RowMapping:
    row = (
        (
            await session.execute(
                select(graph_projection_work)
                .where(
                    graph_projection_work.c.merchant_id == claim.merchant_id,
                    graph_projection_work.c.correlation_id == claim.correlation_id,
                    graph_projection_work.c.status == GraphProjectionStatus.PROCESSING.value,
                    graph_projection_work.c.lease_owner == claim.lease_owner,
                    graph_projection_work.c.attempt_count == claim.attempt_number,
                    graph_projection_work.c.lease_expires_at > func.now(),
                )
                .with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        msg = "projection lease is no longer owned by this worker"
        raise ProjectionLeaseLostError(msg)
    return row


def _validate_receipt(claim: ProjectionWorkClaim, receipt: GraphProjectionReceipt) -> None:
    if receipt.merchant_id != claim.merchant_id or receipt.correlation_id != claim.correlation_id:
        msg = "projection receipt does not match its lease"
        raise ValueError(msg)
    if receipt.state_generation < claim.state_generation:
        msg = "projection receipt generation predates its lease"
        raise ValueError(msg)
    if receipt.projection_epoch != claim.projection_epoch:
        msg = "projection receipt epoch does not match its lease"
        raise ValueError(msg)


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
