"""Audited, cursor-paginated PostgreSQL operator read model."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from chakravyuh.domain.diagnoses import GuardedDiagnosis
from chakravyuh.domain.enums import (
    DiagnosisWorkStatus,
    EntityType,
    IncidentRevisionReason,
    IncidentStatus,
    IncidentType,
)
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.evidence import EvidenceSubgraph
from chakravyuh.domain.incidents import IncidentEvidence, IncidentLifecycle
from chakravyuh.domain.money import Money
from chakravyuh.domain.operators import (
    DiagnosisRecord,
    IncidentDetail,
    IncidentOverview,
    IncidentPage,
    IncidentRevisionRecord,
    IncidentSummary,
)
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.tables import (
    diagnoses,
    diagnosis_work,
    incident_revisions,
    incidents,
    operator_read_audit,
)


class PostgresOperatorReadModel:
    """Expose only bounded current state and immutable evidence with access audit."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def overview(self, *, principal_id: str, request_id: str) -> IncidentOverview:
        principal_id, request_id = _audit_identity(principal_id, request_id)
        async with self._database.transaction() as session:
            status_rows = (
                (
                    await session.execute(
                        select(incidents.c.status, func.count().label("count")).group_by(
                            incidents.c.status
                        )
                    )
                )
                .mappings()
                .all()
            )
            amount_rows = (
                (
                    await session.execute(
                        select(
                            incidents.c.currency,
                            func.sum(incidents.c.amount_subunits).label("amount"),
                        )
                        .where(
                            incidents.c.status != IncidentStatus.RESOLVED.value,
                            incidents.c.amount_subunits.is_not(None),
                        )
                        .group_by(incidents.c.currency)
                    )
                )
                .mappings()
                .all()
            )
            awaiting = int(
                await session.scalar(
                    select(func.count())
                    .select_from(diagnosis_work)
                    .where(
                        diagnosis_work.c.status.in_(
                            (
                                DiagnosisWorkStatus.PENDING.value,
                                DiagnosisWorkStatus.PROCESSING.value,
                            )
                        )
                    )
                )
                or 0
            )
            dead_letters = int(
                await session.scalar(
                    select(func.count())
                    .select_from(diagnosis_work)
                    .where(diagnosis_work.c.status == DiagnosisWorkStatus.DEAD_LETTER.value)
                )
                or 0
            )
            overview = IncidentOverview(
                status_counts={
                    status: next(
                        (int(row["count"]) for row in status_rows if row["status"] == status.value),
                        0,
                    )
                    for status in IncidentStatus
                },
                total_at_risk_subunits={
                    str(row["currency"]): int(row["amount"])
                    for row in amount_rows
                    if row["currency"] is not None
                },
                awaiting_diagnosis_count=awaiting,
                diagnosis_dead_letter_count=dead_letters,
            )
            await _audit(
                session,
                principal_id=principal_id,
                request_id=request_id,
                action="overview",
                resource_type="incident_collection",
                resource_id=None,
                outcome="success",
                details={"status_count": len(overview.status_counts)},
            )
        return overview

    async def list_incidents(
        self,
        *,
        principal_id: str,
        request_id: str,
        statuses: list[str] | tuple[str, ...],
        limit: int,
        cursor: str | None,
    ) -> IncidentPage:
        principal_id, request_id = _audit_identity(principal_id, request_id)
        if not 1 <= limit <= 100:
            msg = "limit must be between 1 and 100"
            raise ValueError(msg)
        selected_statuses = tuple(IncidentStatus(status).value for status in statuses)
        cursor_value = None if cursor is None else _decode_cursor(cursor)

        revision_count = (
            select(func.count())
            .select_from(incident_revisions)
            .where(incident_revisions.c.incident_id == incidents.c.incident_id)
            .correlate(incidents)
            .scalar_subquery()
        )
        latest_disposition = _latest_diagnosis_column(diagnoses.c.disposition)
        latest_confidence = _latest_diagnosis_column(diagnoses.c.confidence)
        latest_diagnosed_at = _latest_diagnosis_column(diagnoses.c.diagnosed_at)
        statement = select(
            incidents,
            revision_count.label("revision_count"),
            latest_disposition.label("diagnosis_disposition"),
            latest_confidence.label("diagnosis_confidence"),
            latest_diagnosed_at.label("latest_diagnosed_at"),
        )
        if selected_statuses:
            statement = statement.where(incidents.c.status.in_(selected_statuses))
        if cursor_value is not None:
            cursor_time, cursor_id = cursor_value
            statement = statement.where(
                or_(
                    incidents.c.last_detected_at < cursor_time,
                    and_(
                        incidents.c.last_detected_at == cursor_time,
                        incidents.c.incident_id < cursor_id,
                    ),
                )
            )
        statement = statement.order_by(
            incidents.c.last_detected_at.desc(),
            incidents.c.incident_id.desc(),
        ).limit(limit + 1)

        async with self._database.transaction() as session:
            rows = (await session.execute(statement)).mappings().all()
            visible = rows[:limit]
            items = tuple(_summary(row) for row in visible)
            next_cursor = None
            if len(rows) > limit and visible:
                last = visible[-1]
                next_cursor = _encode_cursor(last["last_detected_at"], last["incident_id"])
            await _audit(
                session,
                principal_id=principal_id,
                request_id=request_id,
                action="incident_list",
                resource_type="incident_collection",
                resource_id=None,
                outcome="success",
                details={
                    "statuses": list(selected_statuses),
                    "limit": limit,
                    "item_count": len(items),
                    "has_next_page": next_cursor is not None,
                },
            )
        return IncidentPage(items=items, next_cursor=next_cursor)

    async def get_incident(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> IncidentDetail | None:
        principal_id, request_id = _audit_identity(principal_id, request_id)
        async with self._database.transaction() as session:
            incident_row = (
                (
                    await session.execute(
                        select(incidents).where(incidents.c.incident_id == incident_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            detail: IncidentDetail | None = None
            if incident_row is not None:
                revision_rows = (
                    (
                        await session.execute(
                            select(incident_revisions)
                            .where(incident_revisions.c.incident_id == incident_id)
                            .order_by(
                                incident_revisions.c.recorded_at,
                                incident_revisions.c.revision_id,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                diagnosis_row = (
                    (
                        await session.execute(
                            select(diagnoses)
                            .where(diagnoses.c.incident_id == incident_id)
                            .order_by(diagnoses.c.target_version.desc())
                            .limit(1)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                detail = IncidentDetail(
                    incident=_lifecycle(incident_row),
                    revisions=tuple(_revision(row) for row in revision_rows),
                    latest_diagnosis=(None if diagnosis_row is None else _diagnosis(diagnosis_row)),
                )
            await _audit(
                session,
                principal_id=principal_id,
                request_id=request_id,
                action="incident_detail",
                resource_type="incident",
                resource_id=str(incident_id),
                outcome="success" if detail is not None else "not_found",
                details={"diagnosis_available": bool(detail and detail.latest_diagnosis)},
            )
        return detail


def _latest_diagnosis_column(column: Any) -> Any:
    return (
        select(column)
        .where(diagnoses.c.incident_id == incidents.c.incident_id)
        .order_by(diagnoses.c.target_version.desc())
        .limit(1)
        .correlate(incidents)
        .scalar_subquery()
    )


def _summary(row: RowMapping) -> IncidentSummary:
    return IncidentSummary(
        incident_id=row["incident_id"],
        merchant_id=row["merchant_id"],
        correlation_id=row["correlation_id"],
        incident_type=row["incident_type"],
        status=row["status"],
        affected_entity=EntityReference(
            entity_type=EntityType(row["affected_type"]),
            entity_id=row["affected_id"],
        ),
        amount_at_risk=_amount(row),
        occurrence_count=row["occurrence_count"],
        first_detected_at=row["first_detected_at"],
        last_detected_at=row["last_detected_at"],
        revision_count=row["revision_count"],
        diagnosis_disposition=row["diagnosis_disposition"],
        diagnosis_confidence=row["diagnosis_confidence"],
        latest_diagnosed_at=row["latest_diagnosed_at"],
    )


def _lifecycle(row: RowMapping) -> IncidentLifecycle:
    return IncidentLifecycle(
        incident_id=row["incident_id"],
        incident_key=row["incident_key"],
        merchant_id=row["merchant_id"],
        correlation_id=row["correlation_id"],
        incident_type=IncidentType(row["incident_type"]),
        status=IncidentStatus(row["status"]),
        rule_id=row["rule_id"],
        rule_version=row["rule_version"],
        affected_entity=EntityReference(
            entity_type=EntityType(row["affected_type"]),
            entity_id=row["affected_id"],
        ),
        amount_at_risk=_amount(row),
        evidence=tuple(IncidentEvidence.model_validate(item) for item in row["evidence"]),
        finding_hash=row["finding_hash"],
        state_generation=row["state_generation"],
        occurrence_count=row["occurrence_count"],
        first_detected_at=row["first_detected_at"],
        last_detected_at=row["last_detected_at"],
        resolved_at=row["resolved_at"],
        last_evaluation_id=row["last_evaluation_id"],
    )


def _revision(row: RowMapping) -> IncidentRevisionRecord:
    return IncidentRevisionRecord(
        revision_id=row["revision_id"],
        evaluation_id=row["evaluation_id"],
        state_generation=row["state_generation"],
        reason=IncidentRevisionReason(row["reason"]),
        status=IncidentStatus(row["status"]),
        finding_hash=row["finding_hash"],
        recorded_at=row["recorded_at"],
    )


def _diagnosis(row: RowMapping) -> DiagnosisRecord:
    return DiagnosisRecord(
        diagnosis_id=row["diagnosis_id"],
        source_revision_id=row["source_revision_id"],
        target_version=row["target_version"],
        model=row["model"],
        provider_interaction_id=row["provider_interaction_id"],
        prompt_hash=row["prompt_hash"],
        evidence_subgraph=EvidenceSubgraph.model_validate(row["evidence_subgraph"]),
        diagnosis=GuardedDiagnosis.model_validate(row["result"]),
        diagnosed_at=row["diagnosed_at"],
        recorded_at=row["recorded_at"],
    )


def _amount(row: RowMapping) -> Money | None:
    if row["amount_subunits"] is None:
        return None
    return Money(amount_subunits=row["amount_subunits"], currency=row["currency"])


def _encode_cursor(last_detected_at: datetime, incident_id: UUID) -> str:
    value = json.dumps(
        {"last_detected_at": last_detected_at.isoformat(), "incident_id": str(incident_id)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    if not cursor or len(cursor) > 512:
        msg = "invalid incident cursor"
        raise ValueError(msg)
    try:
        padding = "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if not isinstance(value, dict) or set(value) != {"last_detected_at", "incident_id"}:
            raise ValueError
        detected_at = datetime.fromisoformat(value["last_detected_at"])
        if detected_at.tzinfo is None:
            raise ValueError
        return detected_at, UUID(value["incident_id"])
    except (binascii.Error, json.JSONDecodeError, KeyError, TypeError, ValueError) as failure:
        msg = "invalid incident cursor"
        raise ValueError(msg) from failure


def _audit_identity(principal_id: str, request_id: str) -> tuple[str, str]:
    principal_id = principal_id.strip()
    request_id = request_id.strip()
    if not principal_id or len(principal_id) > 64:
        msg = "invalid operator principal"
        raise ValueError(msg)
    if not request_id or len(request_id) > 255:
        msg = "invalid operator request ID"
        raise ValueError(msg)
    return principal_id, request_id


async def _audit(
    session: AsyncSession,
    *,
    principal_id: str,
    request_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    outcome: str,
    details: dict[str, object],
) -> None:
    await session.execute(
        insert(operator_read_audit).values(
            audit_id=uuid4(),
            principal_id=principal_id,
            request_id=request_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            details=details,
        )
    )
