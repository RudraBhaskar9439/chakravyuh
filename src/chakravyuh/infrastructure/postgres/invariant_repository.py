"""Scheduled invariant evaluation and auditable incident reconciliation in PostgreSQL."""

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from chakravyuh.application.invariant_evaluation import InvariantEvaluationBatchResult
from chakravyuh.application.ports import InvariantEvaluator
from chakravyuh.domain.enums import (
    EntityType,
    EventSource,
    IncidentRevisionReason,
    IncidentStatus,
    IncidentType,
    InvariantEvaluationOutcome,
    InvariantEvaluationStatus,
)
from chakravyuh.domain.errors import InvariantEvaluationError, InvariantEvaluationErrorCode
from chakravyuh.domain.events import EntityReference, NormalizedEvent
from chakravyuh.domain.incidents import IncidentEvidence, IncidentLifecycle
from chakravyuh.domain.invariants import InvariantEvaluationResult, InvariantFinding
from chakravyuh.domain.journeys import PaymentJourneyState
from chakravyuh.domain.money import Money
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.tables import (
    incident_revisions,
    incidents,
    invariant_evaluation_work,
    invariant_evaluations,
    normalized_events,
    payment_journey_states,
)


@dataclass(frozen=True, slots=True)
class _LifecycleCounts:
    detected: int = 0
    updated: int = 0
    resolved: int = 0
    reopened: int = 0

    def __add__(self, other: "_LifecycleCounts") -> "_LifecycleCounts":
        return _LifecycleCounts(
            detected=self.detected + other.detected,
            updated=self.updated + other.updated,
            resolved=self.resolved + other.resolved,
            reopened=self.reopened + other.reopened,
        )


class PostgresInvariantEvaluationRepository:
    """Evaluate locked current states and reconcile incidents in one transaction."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def process_batch(
        self,
        *,
        evaluator: InvariantEvaluator,
        worker_id: str,
        batch_size: int,
        max_events_per_journey: int,
    ) -> InvariantEvaluationBatchResult:
        worker_id = _bounded_text(worker_id, field="worker_id", maximum=255)
        if not 1 <= batch_size <= 500:
            msg = "batch_size must be between 1 and 500"
            raise ValueError(msg)
        if not 1 <= max_events_per_journey <= 100_000:
            msg = "max_events_per_journey must be between 1 and 100000"
            raise ValueError(msg)

        completed = 0
        dead_lettered = 0
        lifecycle = _LifecycleCounts()
        async with self._database.transaction() as session:
            evaluated_at = await session.scalar(select(func.now()))
            assert evaluated_at is not None
            work_rows = (
                (
                    await session.execute(
                        select(invariant_evaluation_work)
                        .where(
                            invariant_evaluation_work.c.status
                            == InvariantEvaluationStatus.PENDING.value,
                            invariant_evaluation_work.c.available_at <= evaluated_at,
                        )
                        .order_by(
                            invariant_evaluation_work.c.available_at,
                            invariant_evaluation_work.c.updated_at,
                            invariant_evaluation_work.c.merchant_id,
                            invariant_evaluation_work.c.correlation_id,
                        )
                        .limit(batch_size)
                        .with_for_update(skip_locked=True, of=invariant_evaluation_work)
                    )
                )
                .mappings()
                .all()
            )
            for work in work_rows:
                state_row = await _load_state(session, work)
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
                        raise InvariantEvaluationError(
                            InvariantEvaluationErrorCode.JOURNEY_TOO_LARGE
                        )
                    state = PaymentJourneyState.model_validate(state_row["state"])
                    result = evaluator.evaluate(state, tuple(events), as_of=evaluated_at)
                except InvariantEvaluationError as failure:
                    await _record_dead_letter(
                        session,
                        work=work,
                        evaluation_id=uuid4(),
                        generation=generation,
                        attempt_number=attempt_number,
                        worker_id=worker_id,
                        evaluator_version=evaluator.version,
                        evaluated_at=evaluated_at,
                        error_code=failure.code.value,
                    )
                    dead_lettered += 1
                else:
                    counts = await _record_completed(
                        session,
                        work=work,
                        state_hash=state_row["state_hash"],
                        result=result,
                        generation=generation,
                        attempt_number=attempt_number,
                        worker_id=worker_id,
                    )
                    lifecycle += counts
                    completed += 1

        return InvariantEvaluationBatchResult(
            claimed=len(work_rows),
            completed=completed,
            dead_lettered=dead_lettered,
            incidents_detected=lifecycle.detected,
            incidents_updated=lifecycle.updated,
            incidents_resolved=lifecycle.resolved,
            incidents_reopened=lifecycle.reopened,
        )


async def _load_state(session: AsyncSession, work: RowMapping) -> RowMapping:
    row = (
        (
            await session.execute(
                select(payment_journey_states).where(
                    payment_journey_states.c.merchant_id == work["merchant_id"],
                    payment_journey_states.c.correlation_id == work["correlation_id"],
                )
            )
        )
        .mappings()
        .one()
    )
    return row


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
    work: RowMapping,
    state_hash: str,
    result: InvariantEvaluationResult,
    generation: int,
    attempt_number: int,
    worker_id: str,
) -> _LifecycleCounts:
    evaluation_id = uuid4()
    await session.execute(
        insert(invariant_evaluations).values(
            evaluation_id=evaluation_id,
            merchant_id=work["merchant_id"],
            correlation_id=work["correlation_id"],
            state_generation=generation,
            attempt_number=attempt_number,
            worker_id=worker_id,
            evaluator_version=result.evaluator_version,
            outcome=InvariantEvaluationOutcome.COMPLETED.value,
            error_code=None,
            state_hash=state_hash,
            finding_count=len(result.findings),
            next_evaluation_at=result.next_evaluation_at,
            evaluated_at=result.evaluated_at,
        )
    )
    lifecycle = await _reconcile_incidents(
        session,
        merchant_id=work["merchant_id"],
        correlation_id=work["correlation_id"],
        generation=generation,
        evaluation_id=evaluation_id,
        evaluated_at=result.evaluated_at,
        findings=result.findings,
    )
    scheduled = result.next_evaluation_at is not None
    await session.execute(
        update(invariant_evaluation_work)
        .where(
            invariant_evaluation_work.c.merchant_id == work["merchant_id"],
            invariant_evaluation_work.c.correlation_id == work["correlation_id"],
        )
        .values(
            applied_generation=generation,
            status=(
                InvariantEvaluationStatus.PENDING.value
                if scheduled
                else InvariantEvaluationStatus.COMPLETED.value
            ),
            attempt_count=attempt_number,
            available_at=(result.next_evaluation_at if scheduled else result.evaluated_at),
            last_error_code=None,
            updated_at=func.now(),
        )
    )
    return lifecycle


async def _record_dead_letter(
    session: AsyncSession,
    *,
    work: RowMapping,
    evaluation_id: UUID,
    generation: int,
    attempt_number: int,
    worker_id: str,
    evaluator_version: str,
    evaluated_at: datetime,
    error_code: str,
) -> None:
    await session.execute(
        insert(invariant_evaluations).values(
            evaluation_id=evaluation_id,
            merchant_id=work["merchant_id"],
            correlation_id=work["correlation_id"],
            state_generation=generation,
            attempt_number=attempt_number,
            worker_id=worker_id,
            evaluator_version=evaluator_version,
            outcome=InvariantEvaluationOutcome.DEAD_LETTER.value,
            error_code=error_code,
            state_hash=None,
            finding_count=None,
            next_evaluation_at=None,
            evaluated_at=evaluated_at,
        )
    )
    await session.execute(
        update(invariant_evaluation_work)
        .where(
            invariant_evaluation_work.c.merchant_id == work["merchant_id"],
            invariant_evaluation_work.c.correlation_id == work["correlation_id"],
        )
        .values(
            status=InvariantEvaluationStatus.DEAD_LETTER.value,
            attempt_count=attempt_number,
            last_error_code=error_code,
            updated_at=func.now(),
        )
    )


async def _reconcile_incidents(
    session: AsyncSession,
    *,
    merchant_id: str,
    correlation_id: str,
    generation: int,
    evaluation_id: UUID,
    evaluated_at: datetime,
    findings: tuple[InvariantFinding, ...],
) -> _LifecycleCounts:
    rows = (
        (
            await session.execute(
                select(incidents)
                .where(
                    incidents.c.merchant_id == merchant_id,
                    incidents.c.correlation_id == correlation_id,
                )
                .with_for_update()
            )
        )
        .mappings()
        .all()
    )
    existing = {row["incident_key"]: row for row in rows}
    finding_keys = {finding.incident_key for finding in findings}
    counts = _LifecycleCounts()
    for finding in findings:
        row = existing.get(finding.incident_key)
        if row is None:
            lifecycle = _new_lifecycle(
                finding,
                generation=generation,
                evaluation_id=evaluation_id,
                evaluated_at=evaluated_at,
            )
            await session.execute(insert(incidents).values(**_incident_values(lifecycle)))
            await _append_revision(
                session,
                lifecycle,
                evaluation_id=evaluation_id,
                reason=IncidentRevisionReason.DETECTED,
            )
            counts += _LifecycleCounts(detected=1)
            continue

        previous_status = IncidentStatus(row["status"])
        reopened = previous_status is IncidentStatus.RESOLVED
        changed = row["finding_hash"] != finding.finding_hash
        lifecycle = _updated_lifecycle(
            row,
            finding,
            generation=generation,
            evaluation_id=evaluation_id,
            evaluated_at=evaluated_at,
            reopen=reopened,
        )
        await session.execute(
            update(incidents)
            .where(incidents.c.incident_id == row["incident_id"])
            .values(**_incident_values(lifecycle), updated_at=func.now())
        )
        if reopened or changed:
            reason = IncidentRevisionReason.REOPENED if reopened else IncidentRevisionReason.UPDATED
            await _append_revision(
                session,
                lifecycle,
                evaluation_id=evaluation_id,
                reason=reason,
            )
            counts += _LifecycleCounts(reopened=1) if reopened else _LifecycleCounts(updated=1)

    for row in rows:
        if row["incident_key"] in finding_keys or row["status"] == IncidentStatus.RESOLVED.value:
            continue
        lifecycle = _resolved_lifecycle(
            row,
            generation=generation,
            evaluation_id=evaluation_id,
            evaluated_at=evaluated_at,
        )
        await session.execute(
            update(incidents)
            .where(incidents.c.incident_id == row["incident_id"])
            .values(**_incident_values(lifecycle), updated_at=func.now())
        )
        await _append_revision(
            session,
            lifecycle,
            evaluation_id=evaluation_id,
            reason=IncidentRevisionReason.RESOLVED,
        )
        counts += _LifecycleCounts(resolved=1)
    return counts


def _new_lifecycle(
    finding: InvariantFinding,
    *,
    generation: int,
    evaluation_id: UUID,
    evaluated_at: datetime,
) -> IncidentLifecycle:
    return IncidentLifecycle(
        incident_id=uuid5(NAMESPACE_URL, f"chakravyuh:incident:{finding.incident_key}"),
        incident_key=finding.incident_key,
        merchant_id=finding.merchant_id,
        correlation_id=finding.correlation_id,
        incident_type=finding.incident_type,
        status=IncidentStatus.DETECTED,
        rule_id=finding.rule_id,
        rule_version=finding.rule_version,
        affected_entity=finding.affected_entity,
        amount_at_risk=finding.amount_at_risk,
        evidence=finding.evidence,
        finding_hash=finding.finding_hash,
        state_generation=generation,
        occurrence_count=1,
        first_detected_at=evaluated_at,
        last_detected_at=evaluated_at,
        last_evaluation_id=evaluation_id,
    )


def _updated_lifecycle(
    row: RowMapping,
    finding: InvariantFinding,
    *,
    generation: int,
    evaluation_id: UUID,
    evaluated_at: datetime,
    reopen: bool,
) -> IncidentLifecycle:
    return IncidentLifecycle(
        incident_id=row["incident_id"],
        incident_key=finding.incident_key,
        merchant_id=finding.merchant_id,
        correlation_id=finding.correlation_id,
        incident_type=finding.incident_type,
        status=IncidentStatus.DETECTED if reopen else IncidentStatus(row["status"]),
        rule_id=finding.rule_id,
        rule_version=finding.rule_version,
        affected_entity=finding.affected_entity,
        amount_at_risk=finding.amount_at_risk,
        evidence=finding.evidence,
        finding_hash=finding.finding_hash,
        state_generation=generation,
        occurrence_count=int(row["occurrence_count"]) + int(reopen),
        first_detected_at=row["first_detected_at"],
        last_detected_at=evaluated_at,
        resolved_at=None,
        last_evaluation_id=evaluation_id,
    )


def _resolved_lifecycle(
    row: RowMapping,
    *,
    generation: int,
    evaluation_id: UUID,
    evaluated_at: datetime,
) -> IncidentLifecycle:
    amount = (
        None
        if row["amount_subunits"] is None
        else Money(amount_subunits=row["amount_subunits"], currency=row["currency"])
    )
    return IncidentLifecycle(
        incident_id=row["incident_id"],
        incident_key=row["incident_key"],
        merchant_id=row["merchant_id"],
        correlation_id=row["correlation_id"],
        incident_type=IncidentType(row["incident_type"]),
        status=IncidentStatus.RESOLVED,
        rule_id=row["rule_id"],
        rule_version=row["rule_version"],
        affected_entity=EntityReference(
            entity_type=EntityType(row["affected_type"]),
            entity_id=row["affected_id"],
        ),
        amount_at_risk=amount,
        evidence=tuple(IncidentEvidence.model_validate(item) for item in row["evidence"]),
        finding_hash=row["finding_hash"],
        state_generation=generation,
        occurrence_count=row["occurrence_count"],
        first_detected_at=row["first_detected_at"],
        last_detected_at=row["last_detected_at"],
        resolved_at=evaluated_at,
        last_evaluation_id=evaluation_id,
    )


def _incident_values(lifecycle: IncidentLifecycle) -> dict[str, object]:
    amount = lifecycle.amount_at_risk
    return {
        "incident_id": lifecycle.incident_id,
        "incident_key": lifecycle.incident_key,
        "merchant_id": lifecycle.merchant_id,
        "correlation_id": lifecycle.correlation_id,
        "incident_type": lifecycle.incident_type.value,
        "status": lifecycle.status.value,
        "rule_id": lifecycle.rule_id,
        "rule_version": lifecycle.rule_version,
        "affected_type": lifecycle.affected_entity.entity_type.value,
        "affected_id": lifecycle.affected_entity.entity_id,
        "amount_subunits": None if amount is None else amount.amount_subunits,
        "currency": None if amount is None else amount.currency,
        "evidence": [item.model_dump(mode="json") for item in lifecycle.evidence],
        "finding_hash": lifecycle.finding_hash,
        "state_generation": lifecycle.state_generation,
        "occurrence_count": lifecycle.occurrence_count,
        "first_detected_at": lifecycle.first_detected_at,
        "last_detected_at": lifecycle.last_detected_at,
        "resolved_at": lifecycle.resolved_at,
        "last_evaluation_id": lifecycle.last_evaluation_id,
    }


async def _append_revision(
    session: AsyncSession,
    lifecycle: IncidentLifecycle,
    *,
    evaluation_id: UUID,
    reason: IncidentRevisionReason,
) -> None:
    revision_id = uuid5(
        NAMESPACE_URL,
        f"chakravyuh:incident-revision:{evaluation_id}:{lifecycle.incident_id}:{reason.value}",
    )
    await session.execute(
        insert(incident_revisions).values(
            revision_id=revision_id,
            incident_id=lifecycle.incident_id,
            evaluation_id=evaluation_id,
            state_generation=lifecycle.state_generation,
            reason=reason.value,
            status=lifecycle.status.value,
            finding_hash=lifecycle.finding_hash,
            snapshot=lifecycle.model_dump(mode="json"),
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
