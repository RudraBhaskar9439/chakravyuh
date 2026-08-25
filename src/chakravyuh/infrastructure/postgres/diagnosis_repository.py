"""PostgreSQL leases and immutable audit receipts for grounded diagnosis."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from chakravyuh.domain.diagnoses import DiagnosisReceipt, DiagnosisWorkClaim
from chakravyuh.domain.enums import DiagnosisAttemptOutcome, DiagnosisWorkStatus
from chakravyuh.domain.errors import DiagnosisLeaseLostError, DiagnosisReplayNotAllowedError
from chakravyuh.domain.evidence import DiagnosisSeed
from chakravyuh.domain.incidents import IncidentLifecycle
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.tables import (
    diagnoses,
    diagnosis_attempts,
    diagnosis_replays,
    diagnosis_work,
    incident_revisions,
    payment_journey_revisions,
)


class PostgresDiagnosisRepository:
    """Coordinate at-least-once model work with database-time lease fencing."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def claim_batch(
        self,
        *,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
    ) -> list[DiagnosisWorkClaim]:
        worker_id = _bounded_text(worker_id, field="worker_id", maximum=255)
        if not 1 <= batch_size <= 100:
            msg = "batch_size must be between 1 and 100"
            raise ValueError(msg)
        if not 1 <= lease_seconds <= 3_600:
            msg = "lease_seconds must be between 1 and 3600"
            raise ValueError(msg)

        claims: list[DiagnosisWorkClaim] = []
        async with self._database.transaction() as session:
            database_now = await session.scalar(select(func.now()))
            assert database_now is not None
            lease_expires_at = database_now + timedelta(seconds=lease_seconds)
            rows = (
                (
                    await session.execute(
                        select(diagnosis_work)
                        .where(
                            or_(
                                (diagnosis_work.c.status == DiagnosisWorkStatus.PENDING.value)
                                & (diagnosis_work.c.available_at <= database_now),
                                (diagnosis_work.c.status == DiagnosisWorkStatus.PROCESSING.value)
                                & (diagnosis_work.c.lease_expires_at <= database_now),
                            )
                        )
                        .order_by(
                            diagnosis_work.c.desired_at,
                            diagnosis_work.c.incident_id,
                        )
                        .limit(batch_size)
                        .with_for_update(skip_locked=True, of=diagnosis_work)
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                attempt_number = int(row["attempt_count"]) + 1
                await session.execute(
                    update(diagnosis_work)
                    .where(diagnosis_work.c.incident_id == row["incident_id"])
                    .values(
                        status=DiagnosisWorkStatus.PROCESSING.value,
                        attempt_count=attempt_number,
                        lease_owner=worker_id,
                        lease_expires_at=lease_expires_at,
                        updated_at=func.now(),
                    )
                )
                claims.append(
                    DiagnosisWorkClaim(
                        incident_id=row["incident_id"],
                        source_revision_id=row["source_revision_id"],
                        target_version=row["target_version"],
                        attempt_number=attempt_number,
                        lease_owner=worker_id,
                        leased_until=lease_expires_at,
                    )
                )
        return claims

    async def load(self, claim: DiagnosisWorkClaim) -> DiagnosisSeed:
        async with self._database.session_factory() as session:
            revision = (
                (
                    await session.execute(
                        select(incident_revisions).where(
                            incident_revisions.c.revision_id == claim.source_revision_id,
                            incident_revisions.c.incident_id == claim.incident_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if revision is None:
                msg = "the incident revision selected by this lease no longer exists"
                raise DiagnosisLeaseLostError(msg)
            lifecycle = IncidentLifecycle.model_validate(revision["snapshot"])
            state_hash = await session.scalar(
                select(payment_journey_revisions.c.state_hash).where(
                    payment_journey_revisions.c.merchant_id == lifecycle.merchant_id,
                    payment_journey_revisions.c.correlation_id == lifecycle.correlation_id,
                    payment_journey_revisions.c.generation == revision["state_generation"],
                )
            )
            if state_hash is None:
                msg = "the authoritative journey revision selected by this lease is missing"
                raise DiagnosisLeaseLostError(msg)
        return DiagnosisSeed(
            source_revision_id=claim.source_revision_id,
            source_revision_reason=revision["reason"],
            incident=lifecycle,
            state_generation=revision["state_generation"],
            state_hash=state_hash,
        )

    async def complete(self, claim: DiagnosisWorkClaim, receipt: DiagnosisReceipt) -> None:
        _validate_receipt(claim, receipt)
        diagnosis_id = uuid4()
        effective = receipt.diagnosis.effective_decision
        async with self._database.transaction() as session:
            row = await _locked_lease(session, claim)
            status = (
                DiagnosisWorkStatus.COMPLETED.value
                if int(row["target_version"]) == claim.target_version
                else DiagnosisWorkStatus.PENDING.value
            )
            await session.execute(
                insert(diagnoses).values(
                    diagnosis_id=diagnosis_id,
                    incident_id=claim.incident_id,
                    source_revision_id=claim.source_revision_id,
                    target_version=claim.target_version,
                    model=receipt.model,
                    provider_interaction_id=receipt.provider_interaction_id,
                    prompt_hash=receipt.prompt_hash,
                    subgraph_hash=receipt.evidence_subgraph.subgraph_hash,
                    disposition=effective.disposition.value,
                    confidence=effective.confidence,
                    guard_reason=(
                        None
                        if receipt.diagnosis.guard_reason is None
                        else receipt.diagnosis.guard_reason.value
                    ),
                    evidence_subgraph=receipt.evidence_subgraph.model_dump(mode="json"),
                    result=receipt.diagnosis.model_dump(mode="json"),
                    diagnosed_at=receipt.diagnosed_at,
                )
            )
            await session.execute(
                insert(diagnosis_attempts).values(
                    attempt_id=uuid4(),
                    incident_id=claim.incident_id,
                    source_revision_id=claim.source_revision_id,
                    target_version=claim.target_version,
                    attempt_number=claim.attempt_number,
                    worker_id=claim.lease_owner,
                    outcome=DiagnosisAttemptOutcome.COMPLETED.value,
                    error_code=None,
                    diagnosis_id=diagnosis_id,
                    model=receipt.model,
                )
            )
            await session.execute(
                update(diagnosis_work)
                .where(diagnosis_work.c.incident_id == claim.incident_id)
                .values(
                    applied_version=claim.target_version,
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
        claim: DiagnosisWorkClaim,
        *,
        error_code: str,
        retryable: bool,
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
            dead_lettered = not stale_claim and (not retryable or failure_count >= max_failures)
            outcome = (
                DiagnosisAttemptOutcome.DEAD_LETTER.value
                if dead_lettered
                else DiagnosisAttemptOutcome.RETRY.value
            )
            await session.execute(
                insert(diagnosis_attempts).values(
                    attempt_id=uuid4(),
                    incident_id=claim.incident_id,
                    source_revision_id=claim.source_revision_id,
                    target_version=claim.target_version,
                    attempt_number=claim.attempt_number,
                    worker_id=claim.lease_owner,
                    outcome=outcome,
                    error_code=error_code,
                    diagnosis_id=None,
                    model=None,
                )
            )
            await session.execute(
                update(diagnosis_work)
                .where(diagnosis_work.c.incident_id == claim.incident_id)
                .values(
                    status=(
                        DiagnosisWorkStatus.DEAD_LETTER.value
                        if dead_lettered
                        else DiagnosisWorkStatus.PENDING.value
                    ),
                    failure_count=failure_count,
                    available_at=func.now() + timedelta(seconds=retry_delay_seconds),
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code=None if stale_claim else error_code,
                    updated_at=func.now(),
                )
            )
        return dead_lettered

    async def request_replay(
        self,
        incident_id: UUID,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID:
        requested_by = _bounded_text(requested_by, field="requested_by", maximum=255)
        reason = _bounded_text(reason, field="reason", maximum=2_000)
        replay_id = uuid4()
        async with self._database.transaction() as session:
            row = (
                (
                    await session.execute(
                        select(diagnosis_work)
                        .where(diagnosis_work.c.incident_id == incident_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["status"] != DiagnosisWorkStatus.DEAD_LETTER.value:
                msg = "only a dead-lettered diagnosis can be replayed"
                raise DiagnosisReplayNotAllowedError(msg)
            previous_error = row["last_error_code"]
            if not isinstance(previous_error, str) or not previous_error:
                msg = "dead-lettered diagnosis is missing its stable error code"
                raise DiagnosisReplayNotAllowedError(msg)
            await session.execute(
                insert(diagnosis_replays).values(
                    replay_id=replay_id,
                    incident_id=row["incident_id"],
                    source_revision_id=row["source_revision_id"],
                    target_version=row["target_version"],
                    previous_error_code=previous_error,
                    requested_by=requested_by,
                    reason=reason,
                )
            )
            await session.execute(
                update(diagnosis_work)
                .where(diagnosis_work.c.incident_id == row["incident_id"])
                .values(
                    status=DiagnosisWorkStatus.PENDING.value,
                    failure_count=0,
                    available_at=func.now(),
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code=None,
                    updated_at=func.now(),
                )
            )
        return replay_id


async def _locked_lease(session: AsyncSession, claim: DiagnosisWorkClaim) -> RowMapping:
    row = (
        (
            await session.execute(
                select(diagnosis_work)
                .where(
                    diagnosis_work.c.incident_id == claim.incident_id,
                    diagnosis_work.c.status == DiagnosisWorkStatus.PROCESSING.value,
                    diagnosis_work.c.lease_owner == claim.lease_owner,
                    diagnosis_work.c.attempt_count == claim.attempt_number,
                    diagnosis_work.c.lease_expires_at > func.now(),
                )
                .with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        msg = "diagnosis lease is no longer owned by this worker"
        raise DiagnosisLeaseLostError(msg)
    return row


def _validate_receipt(claim: DiagnosisWorkClaim, receipt: DiagnosisReceipt) -> None:
    evidence = receipt.evidence_subgraph
    if evidence.incident_id != claim.incident_id:
        msg = "diagnosis receipt incident does not match its lease"
        raise ValueError(msg)
    if evidence.source_revision_id != claim.source_revision_id:
        msg = "diagnosis receipt revision does not match its lease"
        raise ValueError(msg)


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    value = value.strip()
    if not value or len(value) > maximum:
        msg = f"{field} must contain between 1 and {maximum} characters"
        raise ValueError(msg)
    return value
