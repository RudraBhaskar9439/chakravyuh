"""Transactional proposal, maker-checker, execution lease, and immutable action audit store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import desc, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from chakravyuh.domain.actions import (
    ActionApproval,
    ActionExecutionClaim,
    ActionExecutionResult,
    ActionProposal,
    ActionProposalSeed,
    ActionView,
    PolicyDecision,
)
from chakravyuh.domain.diagnoses import GuardedDiagnosis
from chakravyuh.domain.enums import (
    ActionApprovalDecision,
    ActionExecutionOperation,
    ActionExecutionOutcome,
    ActionExecutionStatus,
    ActionRisk,
    ActionType,
    DiagnosisDisposition,
    EntityType,
    IncidentStatus,
    IncidentType,
    PolicyOutcome,
)
from chakravyuh.domain.errors import ActionControlError, ActionControlErrorCode
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.evidence import EvidenceSubgraph
from chakravyuh.domain.money import Money
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.postgres.tables import (
    action_access_audit,
    action_approval_decisions,
    action_execution_claims,
    action_execution_results,
    action_execution_work,
    action_mutation_authorizations,
    action_policy_decisions,
    action_proposals,
    diagnoses,
    incident_revisions,
    incidents,
)


class PostgresRecoveryActionRepository:
    """Enforce freshness and separation of duties under database row locks."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def load_seed(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> ActionProposalSeed | None:
        principal_id, request_id = _audit_identity(principal_id, request_id)
        failure: ActionControlError | None = None
        seed: ActionProposalSeed | None = None
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
            if incident_row is None:
                failure = ActionControlError(ActionControlErrorCode.NOT_FOUND)
            else:
                diagnosis_row = await _latest_diagnosis(session, incident_id)
                if diagnosis_row is None:
                    failure = ActionControlError(ActionControlErrorCode.DIAGNOSIS_REQUIRED)
                else:
                    guarded = GuardedDiagnosis.model_validate(diagnosis_row["result"])
                    decision = guarded.effective_decision
                    if decision.disposition is DiagnosisDisposition.ABSTAINED:
                        failure = ActionControlError(ActionControlErrorCode.DIAGNOSIS_ABSTAINED)
                    else:
                        evidence = EvidenceSubgraph.model_validate(
                            diagnosis_row["evidence_subgraph"]
                        )
                        seed = ActionProposalSeed(
                            incident_id=incident_id,
                            source_revision_id=diagnosis_row["source_revision_id"],
                            diagnosis_id=diagnosis_row["diagnosis_id"],
                            merchant_id=incident_row["merchant_id"],
                            incident_type=IncidentType(incident_row["incident_type"]),
                            incident_status=IncidentStatus(incident_row["status"]),
                            target=evidence.affected_entity,
                            amount_at_risk=evidence.amount_at_risk,
                            action_type=decision.recommended_action,
                            rationale=decision.summary,
                            evidence_ids=decision.cited_evidence_ids,
                            confidence=decision.confidence,
                        )
            if failure is not None:
                await _audit(
                    session,
                    principal_id,
                    request_id,
                    action="proposal_create",
                    resource_id=str(incident_id),
                    outcome="not_found"
                    if failure.code is ActionControlErrorCode.NOT_FOUND
                    else "denied",
                    details={"error_code": failure.code.value},
                )
        if failure is not None:
            raise failure
        return seed

    async def create_proposal(
        self,
        proposal: ActionProposal,
        policy: PolicyDecision,
        *,
        principal_id: str,
        request_id: str,
    ) -> ActionView:
        principal_id, request_id = _audit_identity(principal_id, request_id)
        failure: ActionControlError | None = None
        view: ActionView | None = None
        async with self._database.transaction() as session:
            current = await _locked_incident(session, proposal.incident_id)
            if current is None:
                failure = ActionControlError(ActionControlErrorCode.NOT_FOUND)
            elif not await _proposal_is_current(session, proposal, current):
                failure = ActionControlError(ActionControlErrorCode.STALE)
            else:
                inserted = await session.scalar(
                    postgres_insert(action_proposals)
                    .values(**_proposal_values(proposal))
                    .on_conflict_do_nothing(index_elements=[action_proposals.c.idempotency_key])
                    .returning(action_proposals.c.proposal_id)
                )
                if inserted is None:
                    existing = (
                        (
                            await session.execute(
                                select(action_proposals).where(
                                    action_proposals.c.idempotency_key == proposal.idempotency_key
                                )
                            )
                        )
                        .mappings()
                        .one()
                    )
                    await _audit(
                        session,
                        principal_id,
                        request_id,
                        action="proposal_reuse",
                        resource_id=str(existing["proposal_id"]),
                        outcome="success",
                        details={"incident_id": str(proposal.incident_id)},
                    )
                    view = await _view(session, existing["proposal_id"])
                else:
                    await session.execute(
                        insert(action_policy_decisions).values(**_policy_values(policy))
                    )
                    await session.execute(
                        insert(action_execution_work).values(proposal_id=proposal.proposal_id)
                    )
                    await _audit(
                        session,
                        principal_id,
                        request_id,
                        action="proposal_create",
                        resource_id=str(proposal.proposal_id),
                        outcome="success",
                        details={"policy_outcome": policy.outcome.value},
                    )
                    view = await _view(session, proposal.proposal_id)
            if failure is not None:
                await _audit(
                    session,
                    principal_id,
                    request_id,
                    action="proposal_create",
                    resource_id=str(proposal.incident_id),
                    outcome="conflict"
                    if failure.code is not ActionControlErrorCode.NOT_FOUND
                    else "not_found",
                    details={"error_code": failure.code.value},
                )
        if failure is not None:
            raise failure
        assert view is not None
        return view

    async def list_for_incident(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> tuple[ActionView, ...]:
        principal_id, request_id = _audit_identity(principal_id, request_id)
        async with self._database.transaction() as session:
            exists = await session.scalar(
                select(incidents.c.incident_id).where(incidents.c.incident_id == incident_id)
            )
            if exists is None:
                await _audit(
                    session,
                    principal_id,
                    request_id,
                    action="history",
                    resource_id=str(incident_id),
                    outcome="not_found",
                    details={},
                )
                return ()
            proposal_ids = tuple(
                (
                    await session.scalars(
                        select(action_proposals.c.proposal_id)
                        .where(action_proposals.c.incident_id == incident_id)
                        .order_by(
                            action_proposals.c.proposed_at.desc(),
                            action_proposals.c.proposal_id.desc(),
                        )
                    )
                ).all()
            )
            views = tuple([await _view(session, proposal_id) for proposal_id in proposal_ids])
            await _audit(
                session,
                principal_id,
                request_id,
                action="history",
                resource_id=str(incident_id),
                outcome="success",
                details={"item_count": len(views)},
            )
        return views

    async def decide(
        self,
        proposal_id: UUID,
        *,
        principal_id: str,
        request_id: str,
        decision: ActionApprovalDecision,
        rationale: str,
    ) -> ActionView:
        principal_id, request_id = _audit_identity(principal_id, request_id)
        failure: ActionControlError | None = None
        view: ActionView | None = None
        async with self._database.transaction() as session:
            proposal_row = await _locked_proposal(session, proposal_id)
            if proposal_row is None:
                failure = ActionControlError(ActionControlErrorCode.NOT_FOUND)
            else:
                policy_row = await _policy_row(session, proposal_id)
                work = await _locked_work(session, proposal_id)
                if policy_row["outcome"] != PolicyOutcome.REQUIRE_APPROVAL.value:
                    failure = ActionControlError(ActionControlErrorCode.POLICY_DENIED)
                elif work is None or work["status"] != ActionExecutionStatus.READY.value:
                    failure = ActionControlError(ActionControlErrorCode.EXECUTION_TERMINAL)
                elif proposal_row["proposed_by"] == principal_id:
                    failure = ActionControlError(ActionControlErrorCode.MAKER_CHECKER_VIOLATION)
                elif await _row_stale_or_expired(session, proposal_row):
                    failure = ActionControlError(ActionControlErrorCode.STALE)
                else:
                    existing = (
                        (
                            await session.execute(
                                select(action_approval_decisions).where(
                                    action_approval_decisions.c.proposal_id == proposal_id,
                                    action_approval_decisions.c.principal_id == principal_id,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is None:
                        await session.execute(
                            insert(action_approval_decisions).values(
                                approval_id=uuid4(),
                                proposal_id=proposal_id,
                                principal_id=principal_id,
                                request_id=request_id,
                                decision=decision.value,
                                rationale=rationale,
                                decided_at=datetime.now(UTC),
                            )
                        )
                    elif existing["decision"] != decision.value:
                        failure = ActionControlError(ActionControlErrorCode.EXECUTION_TERMINAL)
                    if failure is None:
                        await _audit(
                            session,
                            principal_id,
                            request_id,
                            action="decision",
                            resource_id=str(proposal_id),
                            outcome="success",
                            details={"decision": decision.value},
                        )
                        view = await _view(session, proposal_id)
            if failure is not None:
                await _audit(
                    session,
                    principal_id,
                    request_id,
                    action="decision",
                    resource_id=str(proposal_id),
                    outcome="not_found"
                    if failure.code is ActionControlErrorCode.NOT_FOUND
                    else "denied",
                    details={"error_code": failure.code.value},
                )
        if failure is not None:
            raise failure
        assert view is not None
        return view

    async def claim_execution(
        self,
        proposal_id: UUID,
        *,
        principal_id: str,
        request_id: str,
        lease_seconds: int,
    ) -> ActionExecutionClaim | ActionView:
        principal_id, request_id = _audit_identity(principal_id, request_id)
        if not 5 <= lease_seconds <= 300:
            raise ValueError("execution lease is outside supported bounds")
        failure: ActionControlError | None = None
        result: ActionExecutionClaim | ActionView | None = None
        now = datetime.now(UTC)
        async with self._database.transaction() as session:
            proposal_row = await _locked_proposal(session, proposal_id)
            work = await _locked_work(session, proposal_id)
            if proposal_row is None or work is None:
                failure = ActionControlError(ActionControlErrorCode.NOT_FOUND)
            else:
                policy_row = await _policy_row(session, proposal_id)
                approvals = await _approval_rows(session, proposal_id)
                failure = await _execution_denial(
                    session,
                    proposal_row,
                    policy_row,
                    approvals,
                    now,
                )
                status = ActionExecutionStatus(work["status"])
                if failure is None and status is ActionExecutionStatus.SUCCEEDED:
                    result = await _view(session, proposal_id)
                    await _audit(
                        session,
                        principal_id,
                        request_id,
                        action="execution_idempotent",
                        resource_id=str(proposal_id),
                        outcome="success",
                        details={},
                    )
                elif failure is None and status in {
                    ActionExecutionStatus.BLOCKED,
                    ActionExecutionStatus.UNCERTAIN,
                }:
                    failure = ActionControlError(ActionControlErrorCode.EXECUTION_TERMINAL)
                elif (
                    failure is None
                    and status is ActionExecutionStatus.PROCESSING
                    and work["lease_expires_at"] > now
                ):
                    failure = ActionControlError(ActionControlErrorCode.EXECUTION_IN_PROGRESS)
                elif failure is None:
                    operation = (
                        ActionExecutionOperation.RECONCILE
                        if work["mutation_attempted"]
                        else ActionExecutionOperation.EXECUTE
                    )
                    execution_id = uuid4()
                    attempt_number = int(work["attempt_count"]) + 1
                    leased_until = now + timedelta(seconds=lease_seconds)
                    await session.execute(
                        update(action_execution_work)
                        .where(action_execution_work.c.proposal_id == proposal_id)
                        .values(
                            status=ActionExecutionStatus.PROCESSING.value,
                            attempt_count=attempt_number,
                            latest_execution_id=execution_id,
                            lease_owner=principal_id,
                            lease_expires_at=leased_until,
                            last_error_code=None,
                            updated_at=now,
                        )
                    )
                    await session.execute(
                        insert(action_execution_claims).values(
                            execution_id=execution_id,
                            proposal_id=proposal_id,
                            attempt_number=attempt_number,
                            operation=operation.value,
                            requested_by=principal_id,
                            request_id=request_id,
                            lease_expires_at=leased_until,
                        )
                    )
                    result = ActionExecutionClaim(
                        execution_id=execution_id,
                        attempt_number=attempt_number,
                        operation=operation,
                        proposal=_proposal(proposal_row),
                        requested_by=principal_id,
                        request_id=request_id,
                        lease_expires_at=leased_until,
                    )
                    await _audit(
                        session,
                        principal_id,
                        request_id,
                        action="execution_claim",
                        resource_id=str(proposal_id),
                        outcome="success",
                        details={"attempt_number": attempt_number, "operation": operation.value},
                    )
            if failure is not None:
                await _audit(
                    session,
                    principal_id,
                    request_id,
                    action="execution_claim",
                    resource_id=str(proposal_id),
                    outcome="not_found"
                    if failure.code is ActionControlErrorCode.NOT_FOUND
                    else "denied",
                    details={"error_code": failure.code.value},
                )
        if failure is not None:
            raise failure
        assert result is not None
        return result

    async def mark_mutation_started(self, claim: ActionExecutionClaim) -> None:
        failure: ActionControlError | None = None
        async with self._database.transaction() as session:
            work = await _locked_work(session, claim.proposal.proposal_id)
            now = datetime.now(UTC)
            if (
                work is None
                or work["status"] != ActionExecutionStatus.PROCESSING.value
                or work["latest_execution_id"] != claim.execution_id
                or work["lease_owner"] != claim.requested_by
                or work["lease_expires_at"] <= now
            ):
                failure = ActionControlError(ActionControlErrorCode.LEASE_LOST)
            elif not work["mutation_attempted"]:
                await session.execute(
                    insert(action_mutation_authorizations).values(
                        authorization_id=uuid4(),
                        execution_id=claim.execution_id,
                        proposal_id=claim.proposal.proposal_id,
                    )
                )
                await session.execute(
                    update(action_execution_work)
                    .where(action_execution_work.c.proposal_id == claim.proposal.proposal_id)
                    .values(mutation_attempted=True, updated_at=now)
                )
        if failure is not None:
            raise failure

    async def complete_execution(
        self,
        claim: ActionExecutionClaim,
        result: ActionExecutionResult,
    ) -> ActionView:
        failure: ActionControlError | None = None
        view: ActionView | None = None
        async with self._database.transaction() as session:
            work = await _locked_work(session, claim.proposal.proposal_id)
            if (
                work is None
                or work["status"] != ActionExecutionStatus.PROCESSING.value
                or work["latest_execution_id"] != claim.execution_id
            ):
                failure = ActionControlError(ActionControlErrorCode.LEASE_LOST)
            else:
                await session.execute(
                    insert(action_execution_results).values(
                        result_id=uuid4(),
                        execution_id=result.execution_id,
                        proposal_id=result.proposal_id,
                        outcome=result.outcome.value,
                        error_code=result.error_code,
                        provider_state=(
                            None
                            if result.provider_state is None
                            else result.provider_state.model_dump(mode="json")
                        ),
                        already_applied=result.already_applied,
                        result_hash=result.result_hash,
                        completed_at=result.completed_at,
                    )
                )
                next_status = ActionExecutionStatus(result.outcome.value)
                await session.execute(
                    update(action_execution_work)
                    .where(action_execution_work.c.proposal_id == claim.proposal.proposal_id)
                    .values(
                        status=next_status.value,
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error_code=result.error_code,
                        updated_at=result.completed_at,
                    )
                )
                view = await _view(session, claim.proposal.proposal_id)
        if failure is not None:
            raise failure
        assert view is not None
        return view


async def _execution_denial(
    session: AsyncSession,
    proposal_row: RowMapping,
    policy_row: RowMapping,
    approvals: tuple[RowMapping, ...],
    now: datetime,
) -> ActionControlError | None:
    if policy_row["outcome"] == PolicyOutcome.DENY.value:
        return ActionControlError(ActionControlErrorCode.POLICY_DENIED)
    if any(row["decision"] == ActionApprovalDecision.REJECTED.value for row in approvals):
        return ActionControlError(ActionControlErrorCode.REJECTED)
    if policy_row["outcome"] == PolicyOutcome.REQUIRE_APPROVAL.value and not any(
        row["decision"] == ActionApprovalDecision.APPROVED.value
        and row["principal_id"] != proposal_row["proposed_by"]
        for row in approvals
    ):
        return ActionControlError(ActionControlErrorCode.APPROVAL_REQUIRED)
    if proposal_row["expires_at"] <= now:
        return ActionControlError(ActionControlErrorCode.EXPIRED)
    if await _row_stale_or_expired(session, proposal_row, check_expiry=False):
        return ActionControlError(ActionControlErrorCode.STALE)
    return None


async def _proposal_is_current(
    session: AsyncSession,
    proposal: ActionProposal,
    incident_row: RowMapping,
) -> bool:
    if incident_row["status"] == IncidentStatus.RESOLVED.value:
        return False
    diagnosis_row = await _latest_diagnosis(session, proposal.incident_id)
    revision_id = await _latest_revision_id(session, proposal.incident_id)
    return bool(
        diagnosis_row is not None
        and diagnosis_row["diagnosis_id"] == proposal.diagnosis_id
        and diagnosis_row["source_revision_id"] == proposal.source_revision_id
        and revision_id == proposal.source_revision_id
        and incident_row["merchant_id"] == proposal.merchant_id
        and incident_row["incident_type"] == proposal.incident_type.value
    )


async def _row_stale_or_expired(
    session: AsyncSession,
    proposal_row: RowMapping,
    *,
    check_expiry: bool = True,
) -> bool:
    if check_expiry and proposal_row["expires_at"] <= datetime.now(UTC):
        return True
    current = await _locked_incident(session, proposal_row["incident_id"])
    if current is None or current["status"] == IncidentStatus.RESOLVED.value:
        return True
    latest_diagnosis = await _latest_diagnosis(session, proposal_row["incident_id"])
    return bool(
        await _latest_revision_id(session, proposal_row["incident_id"])
        != proposal_row["source_revision_id"]
        or latest_diagnosis is None
        or latest_diagnosis["diagnosis_id"] != proposal_row["diagnosis_id"]
    )


async def _view(session: AsyncSession, proposal_id: UUID) -> ActionView:
    proposal_row = (
        (
            await session.execute(
                select(action_proposals).where(action_proposals.c.proposal_id == proposal_id)
            )
        )
        .mappings()
        .one()
    )
    policy_row = await _policy_row(session, proposal_id)
    approval_rows = await _approval_rows(session, proposal_id)
    work = (
        (
            await session.execute(
                select(action_execution_work).where(
                    action_execution_work.c.proposal_id == proposal_id
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    result_row = (
        (
            await session.execute(
                select(action_execution_results)
                .where(action_execution_results.c.proposal_id == proposal_id)
                .order_by(action_execution_results.c.completed_at.desc())
                .limit(1)
            )
        )
        .mappings()
        .one_or_none()
    )
    expired = proposal_row["expires_at"] <= datetime.now(UTC)
    stale = await _row_stale_or_expired(session, proposal_row, check_expiry=False)
    return ActionView(
        proposal=_proposal(proposal_row),
        policy=_policy(policy_row),
        approvals=tuple(_approval(row) for row in approval_rows),
        execution_status=(None if work is None else ActionExecutionStatus(work["status"])),
        latest_result=None if result_row is None else _result(result_row),
        stale=stale,
        expired=expired,
    )


async def _latest_diagnosis(session: AsyncSession, incident_id: UUID) -> RowMapping | None:
    return (
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


async def _latest_revision_id(session: AsyncSession, incident_id: UUID) -> UUID | None:
    return await session.scalar(
        select(incident_revisions.c.revision_id)
        .where(incident_revisions.c.incident_id == incident_id)
        .order_by(desc(incident_revisions.c.recorded_at), desc(incident_revisions.c.revision_id))
        .limit(1)
    )


async def _locked_incident(session: AsyncSession, incident_id: UUID) -> RowMapping | None:
    return (
        (
            await session.execute(
                select(incidents).where(incidents.c.incident_id == incident_id).with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )


async def _locked_proposal(session: AsyncSession, proposal_id: UUID) -> RowMapping | None:
    return (
        (
            await session.execute(
                select(action_proposals)
                .where(action_proposals.c.proposal_id == proposal_id)
                .with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )


async def _locked_work(session: AsyncSession, proposal_id: UUID) -> RowMapping | None:
    return (
        (
            await session.execute(
                select(action_execution_work)
                .where(action_execution_work.c.proposal_id == proposal_id)
                .with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )


async def _policy_row(session: AsyncSession, proposal_id: UUID) -> RowMapping:
    return (
        (
            await session.execute(
                select(action_policy_decisions).where(
                    action_policy_decisions.c.proposal_id == proposal_id
                )
            )
        )
        .mappings()
        .one()
    )


async def _approval_rows(session: AsyncSession, proposal_id: UUID) -> tuple[RowMapping, ...]:
    return tuple(
        (
            await session.execute(
                select(action_approval_decisions)
                .where(action_approval_decisions.c.proposal_id == proposal_id)
                .order_by(
                    action_approval_decisions.c.decided_at,
                    action_approval_decisions.c.approval_id,
                )
            )
        )
        .mappings()
        .all()
    )


def _proposal_values(proposal: ActionProposal) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "incident_id": proposal.incident_id,
        "source_revision_id": proposal.source_revision_id,
        "diagnosis_id": proposal.diagnosis_id,
        "merchant_id": proposal.merchant_id,
        "incident_type": proposal.incident_type.value,
        "action_type": proposal.action_type.value,
        "risk": proposal.risk.value,
        "target_type": proposal.target.entity_type.value,
        "target_id": proposal.target.entity_id,
        "amount_subunits": None if proposal.amount is None else proposal.amount.amount_subunits,
        "currency": None if proposal.amount is None else proposal.amount.currency,
        "rationale": proposal.rationale,
        "evidence_ids": list(proposal.evidence_ids),
        "confidence": proposal.confidence,
        "idempotency_key": proposal.idempotency_key,
        "proposal_hash": proposal.proposal_hash,
        "proposed_by": proposal.proposed_by,
        "request_id": proposal.request_id,
        "proposed_at": proposal.proposed_at,
        "expires_at": proposal.expires_at,
    }


def _policy_values(policy: PolicyDecision) -> dict[str, Any]:
    return {
        "decision_id": policy.decision_id,
        "proposal_id": policy.proposal_id,
        "outcome": policy.outcome.value,
        "policy_version": policy.policy_version,
        "reasons": list(policy.reasons),
        "input_hash": policy.input_hash,
        "decided_at": policy.decided_at,
    }


def _proposal(row: RowMapping) -> ActionProposal:
    amount = None
    if row["amount_subunits"] is not None and row["currency"] is not None:
        amount = Money(amount_subunits=row["amount_subunits"], currency=row["currency"])
    return ActionProposal(
        proposal_id=row["proposal_id"],
        incident_id=row["incident_id"],
        source_revision_id=row["source_revision_id"],
        diagnosis_id=row["diagnosis_id"],
        merchant_id=row["merchant_id"],
        incident_type=IncidentType(row["incident_type"]),
        action_type=ActionType(row["action_type"]),
        risk=ActionRisk(row["risk"]),
        target=EntityReference(
            entity_type=EntityType(row["target_type"]),
            entity_id=row["target_id"],
        ),
        amount=amount,
        rationale=row["rationale"],
        evidence_ids=tuple(row["evidence_ids"]),
        confidence=row["confidence"],
        idempotency_key=row["idempotency_key"],
        proposal_hash=row["proposal_hash"],
        proposed_by=row["proposed_by"],
        request_id=row["request_id"],
        proposed_at=row["proposed_at"],
        expires_at=row["expires_at"],
    )


def _policy(row: RowMapping) -> PolicyDecision:
    return PolicyDecision(
        decision_id=row["decision_id"],
        proposal_id=row["proposal_id"],
        outcome=PolicyOutcome(row["outcome"]),
        policy_version=row["policy_version"],
        reasons=tuple(row["reasons"]),
        input_hash=row["input_hash"],
        decided_at=row["decided_at"],
    )


def _approval(row: RowMapping) -> ActionApproval:
    return ActionApproval(
        approval_id=row["approval_id"],
        proposal_id=row["proposal_id"],
        principal_id=row["principal_id"],
        request_id=row["request_id"],
        decision=ActionApprovalDecision(row["decision"]),
        rationale=row["rationale"],
        decided_at=row["decided_at"],
    )


def _result(row: RowMapping) -> ActionExecutionResult:
    return ActionExecutionResult(
        execution_id=row["execution_id"],
        proposal_id=row["proposal_id"],
        outcome=ActionExecutionOutcome(row["outcome"]),
        error_code=row["error_code"],
        provider_state=row["provider_state"],
        already_applied=row["already_applied"],
        completed_at=row["completed_at"],
        result_hash=row["result_hash"],
    )


async def _audit(
    session: AsyncSession,
    principal_id: str,
    request_id: str,
    *,
    action: str,
    resource_id: str | None,
    outcome: str,
    details: dict[str, Any],
) -> None:
    await session.execute(
        insert(action_access_audit).values(
            audit_id=uuid4(),
            principal_id=principal_id,
            request_id=request_id,
            action=action,
            resource_id=resource_id,
            outcome=outcome,
            details=details,
        )
    )


def _audit_identity(principal_id: str, request_id: str) -> tuple[str, str]:
    normalized_principal = principal_id.strip()
    normalized_request = request_id.strip()
    if not 1 <= len(normalized_principal) <= 64 or not 1 <= len(normalized_request) <= 255:
        raise ValueError("audit identity is outside supported bounds")
    return normalized_principal, normalized_request
