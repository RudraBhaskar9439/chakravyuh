"""Real PostgreSQL proofs for invariant evaluation and incident lifecycle."""

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from chakravyuh.application.invariant_evaluation import InvariantEvaluationBatchResult
from chakravyuh.config import Settings
from chakravyuh.domain.enums import (
    EntityType,
    EventSource,
    IncidentRevisionReason,
    IncidentStatus,
    InvariantEvaluationOutcome,
    InvariantEvaluationStatus,
    PaymentStatus,
)
from chakravyuh.domain.events import EntityReference, NormalizedEvent
from chakravyuh.domain.invariants import DeterministicPaymentInvariantEvaluator, InvariantPolicy
from chakravyuh.domain.journeys import (
    JourneyEntityState,
    PaymentJourneyState,
    journey_state_hash,
)
from chakravyuh.domain.money import Money
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.invariant_repository import (
    PostgresInvariantEvaluationRepository,
)
from chakravyuh.infrastructure.postgres.tables import (
    graph_projection_work,
    incident_revisions,
    incidents,
    invariant_evaluation_work,
    invariant_evaluations,
    journey_reduction_work,
    normalization_work,
    normalized_events,
    payment_journey_states,
    webhook_events,
)

TEST_POSTGRES_DSN = os.environ.get("CHAKRAVYUH_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(
    TEST_POSTGRES_DSN is None,
    reason="CHAKRAVYUH_TEST_POSTGRES_DSN is required for PostgreSQL integration proofs",
)


class ExplodingEvaluator:
    version = "exploding-invariant-v1"

    def evaluate(
        self,
        state: PaymentJourneyState,
        events: tuple[NormalizedEvent, ...],
        *,
        as_of: datetime,
    ) -> object:
        del state, events, as_of
        raise RuntimeError("simulated invariant failure")


def _database() -> Database:
    assert TEST_POSTGRES_DSN is not None
    return Database(Settings(environment="test", postgres_dsn=TEST_POSTGRES_DSN))


def _evaluator() -> DeterministicPaymentInvariantEvaluator:
    return DeterministicPaymentInvariantEvaluator(
        InvariantPolicy(
            captured_order_paid_grace_seconds=1,
            authorized_capture_grace_seconds=1,
            failed_recovery_grace_seconds=1,
            stale_recovery_link_grace_seconds=1,
        )
    )


def _captured_state(
    merchant_id: str,
    order_id: str,
    payment_id: str,
    *,
    generation: int,
    amount_subunits: int = 10_000,
    order_paid: bool = False,
    occurred_at: datetime | None = None,
) -> PaymentJourneyState:
    occurred = occurred_at or datetime.now(UTC) - timedelta(minutes=5)
    payment_event_id = uuid4()
    entities = [
        JourneyEntityState(
            entity=EntityReference(entity_type=EntityType.PAYMENT, entity_id=payment_id),
            provider_status="captured",
            effective_payment_status=PaymentStatus.CAPTURED,
            amount=Money(amount_subunits=amount_subunits, currency="INR"),
            amount_refunded_subunits=0,
            order_id=order_id,
            first_occurred_at=occurred,
            last_occurred_at=occurred,
            latest_event_id=payment_event_id,
            event_count=1,
        )
    ]
    if order_paid:
        entities.append(
            JourneyEntityState(
                entity=EntityReference(
                    entity_type=EntityType.RAZORPAY_ORDER,
                    entity_id=order_id,
                ),
                provider_status="paid",
                amount=Money(amount_subunits=amount_subunits, currency="INR"),
                amount_paid_subunits=amount_subunits,
                amount_due_subunits=0,
                first_occurred_at=occurred,
                last_occurred_at=occurred,
                latest_event_id=uuid4(),
                event_count=1,
            )
        )
    latest_event_id = entities[-1].latest_event_id
    return PaymentJourneyState(
        merchant_id=merchant_id,
        correlation_id=order_id,
        event_count=len(entities),
        first_occurred_at=occurred,
        last_occurred_at=occurred,
        latest_event_id=latest_event_id,
        entities=tuple(entities),
    )


def _authorized_state(
    merchant_id: str,
    order_id: str,
    payment_id: str,
) -> PaymentJourneyState:
    occurred = datetime.now(UTC)
    event_id = uuid4()
    return PaymentJourneyState(
        merchant_id=merchant_id,
        correlation_id=order_id,
        event_count=1,
        first_occurred_at=occurred,
        last_occurred_at=occurred,
        latest_event_id=event_id,
        entities=(
            JourneyEntityState(
                entity=EntityReference(entity_type=EntityType.PAYMENT, entity_id=payment_id),
                provider_status="authorized",
                effective_payment_status=PaymentStatus.AUTHORIZED,
                amount=Money(amount_subunits=10_000, currency="INR"),
                amount_refunded_subunits=0,
                order_id=order_id,
                first_occurred_at=occurred,
                last_occurred_at=occurred,
                latest_event_id=event_id,
                event_count=1,
            ),
        ),
    )


async def _put_state(
    database: Database,
    state: PaymentJourneyState,
    *,
    generation: int,
) -> None:
    values = {
        "generation": generation,
        "event_count": state.event_count,
        "reducer_version": "invariant-integration-fixture-v1",
        "state_hash": journey_state_hash(state),
        "last_occurred_at": state.last_occurred_at,
        "state": state.model_dump(mode="json"),
        "updated_at": func.now(),
    }
    async with database.transaction() as session:
        existing = await session.scalar(
            select(func.count())
            .select_from(payment_journey_states)
            .where(
                payment_journey_states.c.merchant_id == state.merchant_id,
                payment_journey_states.c.correlation_id == state.correlation_id,
            )
        )
        if existing:
            await session.execute(
                update(payment_journey_states)
                .where(
                    payment_journey_states.c.merchant_id == state.merchant_id,
                    payment_journey_states.c.correlation_id == state.correlation_id,
                )
                .values(**values)
            )
        else:
            await session.execute(
                insert(payment_journey_states).values(
                    merchant_id=state.merchant_id,
                    correlation_id=state.correlation_id,
                    **values,
                )
            )


async def _drain_invariants(database: Database) -> None:
    repository = PostgresInvariantEvaluationRepository(database)
    while True:
        result = await repository.process_batch(
            evaluator=_evaluator(),
            worker_id="invariant-test-drain",
            batch_size=500,
            max_events_per_journey=100_000,
        )
        if result.claimed == 0:
            return


async def _cleanup_state_fixture(database: Database, merchant_id: str) -> None:
    """Remove replaceable operational fixtures; immutable audit evidence remains."""

    async with database.transaction() as session:
        raw_event_ids = select(normalized_events.c.source_webhook_event_id).where(
            normalized_events.c.merchant_id == merchant_id
        )
        await session.execute(
            delete(normalization_work).where(
                normalization_work.c.webhook_event_id.in_(raw_event_ids)
            )
        )
        await session.execute(
            delete(journey_reduction_work).where(
                journey_reduction_work.c.merchant_id == merchant_id
            )
        )
        await session.execute(
            delete(invariant_evaluation_work).where(
                invariant_evaluation_work.c.merchant_id == merchant_id
            )
        )
        await session.execute(
            delete(graph_projection_work).where(graph_projection_work.c.merchant_id == merchant_id)
        )
        await session.execute(
            delete(payment_journey_states).where(
                payment_journey_states.c.merchant_id == merchant_id
            )
        )


async def _process_one(
    database: Database,
    *,
    worker_id: str = "invariant-worker",
) -> InvariantEvaluationBatchResult:
    return await PostgresInvariantEvaluationRepository(database).process_batch(
        evaluator=_evaluator(),
        worker_id=worker_id,
        batch_size=1,
        max_events_per_journey=100,
    )


async def test_timed_evaluation_is_scheduled_without_premature_incident() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    try:
        await _drain_invariants(database)
        await _put_state(
            database,
            _authorized_state(merchant_id, order_id, f"pay_{uuid4().hex}"),
            generation=1,
        )

        result = await _process_one(database)
        async with database.session_factory() as session:
            work = (
                (
                    await session.execute(
                        select(invariant_evaluation_work).where(
                            invariant_evaluation_work.c.merchant_id == merchant_id,
                            invariant_evaluation_work.c.correlation_id == order_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            incident_count = await session.scalar(
                select(func.count())
                .select_from(incidents)
                .where(incidents.c.merchant_id == merchant_id)
            )
        assert result.completed == 1
        assert work["status"] == InvariantEvaluationStatus.PENDING.value
        assert work["applied_generation"] == 1
        assert work["available_at"] > datetime.now(UTC)
        assert incident_count == 0
    finally:
        await _cleanup_state_fixture(database, merchant_id)
        await database.close()


async def test_incident_detect_update_resolve_and_reopen_are_audited() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    payment_id = f"pay_{uuid4().hex}"
    try:
        await _drain_invariants(database)

        await _put_state(
            database,
            _captured_state(merchant_id, order_id, payment_id, generation=1),
            generation=1,
        )
        detected = await _process_one(database)

        await _put_state(
            database,
            _captured_state(
                merchant_id,
                order_id,
                payment_id,
                generation=2,
                amount_subunits=12_000,
            ),
            generation=2,
        )
        changed = await _process_one(database)

        await _put_state(
            database,
            _captured_state(
                merchant_id,
                order_id,
                payment_id,
                generation=3,
                amount_subunits=12_000,
                order_paid=True,
            ),
            generation=3,
        )
        resolved = await _process_one(database)

        await _put_state(
            database,
            _captured_state(
                merchant_id,
                order_id,
                payment_id,
                generation=4,
                amount_subunits=12_000,
            ),
            generation=4,
        )
        reopened = await _process_one(database)

        async with database.session_factory() as session:
            incident = (
                (
                    await session.execute(
                        select(incidents).where(incidents.c.merchant_id == merchant_id)
                    )
                )
                .mappings()
                .one()
            )
            revisions = (
                (
                    await session.execute(
                        select(incident_revisions)
                        .where(incident_revisions.c.incident_id == incident["incident_id"])
                        .order_by(incident_revisions.c.recorded_at)
                    )
                )
                .mappings()
                .all()
            )
            evaluations = await session.scalar(
                select(func.count())
                .select_from(invariant_evaluations)
                .where(invariant_evaluations.c.merchant_id == merchant_id)
            )

        assert detected.incidents_detected == 1
        assert changed.incidents_updated == 1
        assert resolved.incidents_resolved == 1
        assert reopened.incidents_reopened == 1
        assert incident["status"] == IncidentStatus.DETECTED.value
        assert incident["occurrence_count"] == 2
        assert incident["resolved_at"] is None
        assert [row["reason"] for row in revisions] == [
            IncidentRevisionReason.DETECTED.value,
            IncidentRevisionReason.UPDATED.value,
            IncidentRevisionReason.RESOLVED.value,
            IncidentRevisionReason.REOPENED.value,
        ]
        assert evaluations == 4
        assert all(isinstance(row["snapshot"], dict) for row in revisions)
    finally:
        await _cleanup_state_fixture(database, merchant_id)
        await database.close()


async def test_identical_finding_updates_seen_time_without_duplicate_revision() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    payment_id = f"pay_{uuid4().hex}"
    state = _captured_state(merchant_id, order_id, payment_id, generation=1)
    try:
        await _drain_invariants(database)
        await _put_state(database, state, generation=1)
        await _process_one(database)
        await _put_state(database, state, generation=2)
        second = await _process_one(database)

        async with database.session_factory() as session:
            revision_count = await session.scalar(
                select(func.count())
                .select_from(incident_revisions)
                .join(incidents, incident_revisions.c.incident_id == incidents.c.incident_id)
                .where(incidents.c.merchant_id == merchant_id)
            )
            incident = (
                (
                    await session.execute(
                        select(incidents).where(incidents.c.merchant_id == merchant_id)
                    )
                )
                .mappings()
                .one()
            )
        assert second.incidents_updated == 0
        assert revision_count == 1
        assert incident["state_generation"] == 2
        assert incident["occurrence_count"] == 1
    finally:
        await _cleanup_state_fixture(database, merchant_id)
        await database.close()


async def test_concurrent_workers_claim_distinct_states() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    try:
        await _drain_invariants(database)
        for _ in range(6):
            order_id = f"order_{uuid4().hex}"
            await _put_state(
                database,
                _captured_state(
                    merchant_id,
                    order_id,
                    f"pay_{uuid4().hex}",
                    generation=1,
                ),
                generation=1,
            )

        repository = PostgresInvariantEvaluationRepository(database)
        results = await asyncio.gather(
            *(
                repository.process_batch(
                    evaluator=_evaluator(),
                    worker_id=f"invariant-worker-{number}",
                    batch_size=2,
                    max_events_per_journey=100,
                )
                for number in range(3)
            )
        )

        assert sum(result.claimed for result in results) == 6
        assert sum(result.incidents_detected for result in results) == 6
        async with database.session_factory() as session:
            incident_count = await session.scalar(
                select(func.count())
                .select_from(incidents)
                .where(incidents.c.merchant_id == merchant_id)
            )
        assert incident_count == 6
    finally:
        await _cleanup_state_fixture(database, merchant_id)
        await database.close()


async def _insert_normalized_history(
    database: Database,
    *,
    merchant_id: str,
    correlation_id: str,
    payment_id: str,
    count: int,
) -> None:
    occurred = datetime.now(UTC) - timedelta(minutes=5)
    async with database.transaction() as session:
        for number in range(count):
            raw_id = uuid4()
            raw_body = b"{}"
            source_event_id = f"evt_{uuid4().hex}"
            await session.execute(
                insert(webhook_events).values(
                    event_id=raw_id,
                    merchant_id=merchant_id,
                    source=EventSource.RAZORPAY_WEBHOOK.value,
                    source_event_id=source_event_id,
                    event_type="payment.captured",
                    account_id="test-account",
                    occurred_at=occurred + timedelta(seconds=number),
                    observed_at=occurred + timedelta(minutes=1),
                    payload={},
                    raw_body=raw_body,
                    body_sha256=hashlib.sha256(raw_body).hexdigest(),
                )
            )
            await session.execute(
                insert(normalized_events).values(
                    event_id=uuid4(),
                    source_webhook_event_id=raw_id,
                    schema_version=1,
                    merchant_id=merchant_id,
                    source=EventSource.RAZORPAY_WEBHOOK.value,
                    source_event_id=source_event_id,
                    event_type="payment.captured",
                    subject_type=EntityType.PAYMENT.value,
                    subject_id=payment_id,
                    occurred_at=occurred + timedelta(seconds=number),
                    observed_at=occurred + timedelta(minutes=1),
                    correlation_id=correlation_id,
                    payload={"id": payment_id, "status": "captured"},
                    normalizer_version="invariant-integration-fixture-v1",
                )
            )


async def test_oversized_history_dead_letters_once_with_stable_audit() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    payment_id = f"pay_{uuid4().hex}"
    repository = PostgresInvariantEvaluationRepository(database)
    try:
        await _drain_invariants(database)
        await _insert_normalized_history(
            database,
            merchant_id=merchant_id,
            correlation_id=order_id,
            payment_id=payment_id,
            count=2,
        )
        await _put_state(
            database,
            _captured_state(merchant_id, order_id, payment_id, generation=1),
            generation=1,
        )

        first = await repository.process_batch(
            evaluator=_evaluator(),
            worker_id="bounded-invariant-worker",
            batch_size=1,
            max_events_per_journey=1,
        )
        second = await repository.process_batch(
            evaluator=_evaluator(),
            worker_id="bounded-invariant-worker",
            batch_size=1,
            max_events_per_journey=1,
        )

        async with database.session_factory() as session:
            work = (
                (
                    await session.execute(
                        select(invariant_evaluation_work).where(
                            invariant_evaluation_work.c.merchant_id == merchant_id,
                            invariant_evaluation_work.c.correlation_id == order_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            evaluation = (
                (
                    await session.execute(
                        select(invariant_evaluations).where(
                            invariant_evaluations.c.merchant_id == merchant_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            incident_count = await session.scalar(
                select(func.count())
                .select_from(incidents)
                .where(incidents.c.merchant_id == merchant_id)
            )
        assert first.dead_lettered == 1
        assert second.claimed == 0
        assert work["status"] == InvariantEvaluationStatus.DEAD_LETTER.value
        assert work["attempt_count"] == 1
        assert evaluation["outcome"] == InvariantEvaluationOutcome.DEAD_LETTER.value
        assert evaluation["error_code"] == "invariant_journey_too_large"
        assert incident_count == 0
    finally:
        await _cleanup_state_fixture(database, merchant_id)
        await database.close()


async def test_unexpected_failure_rolls_back_work_and_all_audit_rows() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    try:
        await _drain_invariants(database)
        await _put_state(
            database,
            _captured_state(
                merchant_id,
                order_id,
                f"pay_{uuid4().hex}",
                generation=1,
            ),
            generation=1,
        )
        with pytest.raises(RuntimeError, match="simulated invariant failure"):
            await PostgresInvariantEvaluationRepository(database).process_batch(
                evaluator=ExplodingEvaluator(),  # type: ignore[arg-type]
                worker_id="exploding-invariant-worker",
                batch_size=1,
                max_events_per_journey=100,
            )

        async with database.session_factory() as session:
            work = (
                (
                    await session.execute(
                        select(invariant_evaluation_work).where(
                            invariant_evaluation_work.c.merchant_id == merchant_id,
                            invariant_evaluation_work.c.correlation_id == order_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            evaluations = await session.scalar(
                select(func.count())
                .select_from(invariant_evaluations)
                .where(invariant_evaluations.c.merchant_id == merchant_id)
            )
        assert work["status"] == InvariantEvaluationStatus.PENDING.value
        assert work["attempt_count"] == 0
        assert evaluations == 0
    finally:
        await _cleanup_state_fixture(database, merchant_id)
        await database.close()


async def test_invariant_audit_tables_reject_update_delete_and_truncate() -> None:
    database = _database()
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    try:
        await _drain_invariants(database)
        await _put_state(
            database,
            _captured_state(
                merchant_id,
                order_id,
                f"pay_{uuid4().hex}",
                generation=1,
            ),
            generation=1,
        )
        await _process_one(database)
        async with database.session_factory() as session:
            incident_id = await session.scalar(
                select(incidents.c.incident_id).where(incidents.c.merchant_id == merchant_id)
            )
        assert isinstance(incident_id, UUID)

        statements: list[tuple[str, dict[str, Any]]] = [
            (
                "UPDATE ledger.invariant_evaluations SET worker_id = 'changed' "
                "WHERE merchant_id = :merchant_id",
                {"merchant_id": merchant_id},
            ),
            (
                "DELETE FROM ledger.incident_revisions WHERE incident_id = :incident_id",
                {"incident_id": incident_id},
            ),
            ("TRUNCATE ledger.invariant_evaluations CASCADE", {}),
        ]
        for statement, parameters in statements:
            with pytest.raises(DBAPIError, match="append-only"):
                async with database.transaction() as session:
                    await session.execute(text(statement), parameters)
    finally:
        await _cleanup_state_fixture(database, merchant_id)
        await database.close()


async def test_repository_rejects_unbounded_operational_inputs() -> None:
    database = _database()
    repository = PostgresInvariantEvaluationRepository(database)
    try:
        with pytest.raises(ValueError, match="worker_id"):
            await repository.process_batch(
                evaluator=_evaluator(),
                worker_id=" ",
                batch_size=1,
                max_events_per_journey=100,
            )
        with pytest.raises(ValueError, match="batch_size"):
            await repository.process_batch(
                evaluator=_evaluator(),
                worker_id="worker",
                batch_size=0,
                max_events_per_journey=100,
            )
        with pytest.raises(ValueError, match="max_events_per_journey"):
            await repository.process_batch(
                evaluator=_evaluator(),
                worker_id="worker",
                batch_size=1,
                max_events_per_journey=0,
            )
    finally:
        await database.close()
