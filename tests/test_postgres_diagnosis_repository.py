"""Real PostgreSQL, Neo4j, and diagnosis receipt proofs."""

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from chakravyuh.application.evidence_assembly import AssembleEvidenceSubgraph
from chakravyuh.application.graph_projection import ProcessGraphProjectionBatch
from chakravyuh.application.recovery_actions import RecoveryActionControlPlane
from chakravyuh.config import Settings
from chakravyuh.domain.action_policy import (
    DeterministicRecoveryPolicy,
    RecoveryPolicyConfig,
)
from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.diagnoses import (
    DiagnosisDecision,
    DiagnosisReceipt,
    diagnosis_prompt,
    guard_diagnosis,
)
from chakravyuh.domain.enums import (
    ActionApprovalDecision,
    ActionExecutionStatus,
    ActionType,
    DiagnosisDisposition,
    DiagnosisRootCause,
    DiagnosisWorkStatus,
    EventSource,
    IncidentRevisionReason,
    IncidentStatus,
    InvariantEvaluationOutcome,
    PaymentStatus,
    PolicyOutcome,
)
from chakravyuh.domain.errors import (
    ActionControlError,
    ActionControlErrorCode,
    DiagnosisLeaseLostError,
)
from chakravyuh.domain.invariants import DeterministicPaymentInvariantEvaluator, InvariantPolicy
from chakravyuh.domain.journeys import TemporalPaymentJourneyReducer
from chakravyuh.domain.money import Money
from chakravyuh.domain.webhooks import RawWebhookEvent
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.neo4j.evidence_reader import Neo4jEvidenceReader
from chakravyuh.infrastructure.neo4j.projector import Neo4jPaymentGraphProjector
from chakravyuh.infrastructure.postgres.action_repository import (
    PostgresRecoveryActionRepository,
)
from chakravyuh.infrastructure.postgres.diagnosis_repository import PostgresDiagnosisRepository
from chakravyuh.infrastructure.postgres.graph_projection_repository import (
    PostgresGraphProjectionRepository,
)
from chakravyuh.infrastructure.postgres.invariant_repository import (
    PostgresInvariantEvaluationRepository,
)
from chakravyuh.infrastructure.postgres.journey_reduction_repository import (
    PostgresJourneyReductionRepository,
)
from chakravyuh.infrastructure.postgres.normalization_repository import (
    PostgresNormalizationRepository,
)
from chakravyuh.infrastructure.postgres.operator_read_model import PostgresOperatorReadModel
from chakravyuh.infrastructure.postgres.tables import (
    action_access_audit,
    action_approval_decisions,
    action_execution_claims,
    action_execution_results,
    action_mutation_authorizations,
    action_policy_decisions,
    action_proposals,
    diagnoses,
    diagnosis_attempts,
    diagnosis_work,
    incident_revisions,
    incidents,
    invariant_evaluations,
    operator_read_audit,
)
from chakravyuh.infrastructure.postgres.webhook_event_store import PostgresWebhookEventStore
from chakravyuh.infrastructure.razorpay.normalizer import RazorpayWebhookNormalizer

TEST_POSTGRES_DSN = os.environ.get("CHAKRAVYUH_TEST_POSTGRES_DSN")
TEST_NEO4J_URI = os.environ.get("CHAKRAVYUH_TEST_NEO4J_URI")
TEST_NEO4J_PASSWORD = os.environ.get(
    "CHAKRAVYUH_TEST_NEO4J_PASSWORD",
    "local-development-only",
)
pytestmark = pytest.mark.skipif(
    TEST_POSTGRES_DSN is None or TEST_NEO4J_URI is None,
    reason="PostgreSQL and Neo4j endpoints are required for diagnosis integration proofs",
)


def _settings() -> Settings:
    assert TEST_POSTGRES_DSN is not None
    assert TEST_NEO4J_URI is not None
    return Settings(
        environment="test",
        postgres_dsn=TEST_POSTGRES_DSN,
        neo4j_uri=TEST_NEO4J_URI,
        neo4j_password=SecretStr(TEST_NEO4J_PASSWORD),
    )


def _captured_payment(merchant_id: str, order_id: str, payment_id: str) -> RawWebhookEvent:
    observed_at = datetime.now(UTC)
    occurred_at = observed_at - timedelta(minutes=5)
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "status": "captured",
                    "captured": True,
                    "amount": 10_000,
                    "currency": "INR",
                }
            }
        },
    }
    return RawWebhookEvent(
        merchant_id=merchant_id,
        source=EventSource.RAZORPAY_WEBHOOK,
        source_event_id=f"event-{uuid4()}",
        event_type="payment.captured",
        account_id="test-account",
        occurred_at=occurred_at,
        observed_at=observed_at,
        payload=payload,
        raw_body=json.dumps(payload, sort_keys=True).encode(),
    )


def _authorized_payment(merchant_id: str, order_id: str, payment_id: str) -> RawWebhookEvent:
    observed_at = datetime.now(UTC)
    occurred_at = observed_at - timedelta(minutes=20)
    payload = {
        "event": "payment.authorized",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "status": "authorized",
                    "captured": False,
                    "amount": 10_000,
                    "currency": "INR",
                }
            }
        },
    }
    return RawWebhookEvent(
        merchant_id=merchant_id,
        source=EventSource.RAZORPAY_WEBHOOK,
        source_event_id=f"event-{uuid4()}",
        event_type="payment.authorized",
        account_id="test-account",
        occurred_at=occurred_at,
        observed_at=observed_at,
        payload=payload,
        raw_body=json.dumps(payload, sort_keys=True).encode(),
    )


class _CaptureGateway:
    def __init__(self, payment_id: str) -> None:
        self.payment_id = payment_id
        self.captured = False
        self.fetch_count = 0
        self.capture_count = 0

    async def fetch_payment(self, payment_id: str) -> ProviderPaymentState:
        assert payment_id == self.payment_id
        self.fetch_count += 1
        return self._state()

    async def capture_payment(self, payment_id: str, amount: Money) -> ProviderPaymentState:
        assert payment_id == self.payment_id
        assert amount == Money(amount_subunits=10_000, currency="INR")
        self.capture_count += 1
        self.captured = True
        return self._state()

    async def close(self) -> None:
        return None

    def _state(self) -> ProviderPaymentState:
        return ProviderPaymentState(
            payment_id=self.payment_id,
            status=PaymentStatus.CAPTURED if self.captured else PaymentStatus.AUTHORIZED,
            amount=Money(amount_subunits=10_000, currency="INR"),
            captured=self.captured,
        )


async def _prepare_incident(
    database: Database,
    projector: Neo4jPaymentGraphProjector,
    *,
    merchant_id: str,
    order_id: str,
    payment_id: str,
    raw_event: RawWebhookEvent | None = None,
) -> UUID:
    assert await PostgresWebhookEventStore(database).append(
        raw_event or _captured_payment(merchant_id, order_id, payment_id)
    )
    normalizer = PostgresNormalizationRepository(database)
    while (
        await normalizer.process_batch(
            normalizer=RazorpayWebhookNormalizer(),
            worker_id="diagnosis-proof-normalizer",
            batch_size=500,
        )
    ).claimed:
        pass
    reducer = PostgresJourneyReductionRepository(database)
    while (
        await reducer.process_batch(
            reducer=TemporalPaymentJourneyReducer(),
            worker_id="diagnosis-proof-reducer",
            batch_size=500,
            max_events_per_journey=100_000,
        )
    ).claimed:
        pass
    projection = ProcessGraphProjectionBatch(
        PostgresGraphProjectionRepository(database),
        projector,
        worker_id="diagnosis-proof-projector",
        batch_size=500,
        lease_seconds=30,
        max_failures=5,
        retry_delay_seconds=0,
    )
    while (await projection.execute()).claimed:
        pass
    evaluator = DeterministicPaymentInvariantEvaluator(
        InvariantPolicy(
            captured_order_paid_grace_seconds=1,
            authorized_capture_grace_seconds=1,
            failed_recovery_grace_seconds=1,
            stale_recovery_link_grace_seconds=1,
        )
    )
    invariants = PostgresInvariantEvaluationRepository(database)
    while (
        await invariants.process_batch(
            evaluator=evaluator,
            worker_id="diagnosis-proof-invariants",
            batch_size=500,
            max_events_per_journey=100_000,
        )
    ).claimed:
        pass
    async with database.session_factory() as session:
        incident_id = await session.scalar(
            select(incidents.c.incident_id).where(
                incidents.c.merchant_id == merchant_id,
                incidents.c.correlation_id == order_id,
            )
        )
    assert isinstance(incident_id, UUID)
    async with database.transaction() as session:
        await session.execute(
            update(diagnosis_work)
            .where(diagnosis_work.c.incident_id == incident_id)
            .values(desired_at=func.now() - timedelta(days=1))
        )
    return incident_id


async def _claim_incident(
    repository: PostgresDiagnosisRepository,
    incident_id: UUID,
    *,
    worker_id: str,
) -> Any:
    claims = await repository.claim_batch(
        worker_id=worker_id,
        batch_size=100,
        lease_seconds=30,
    )
    return next(claim for claim in claims if claim.incident_id == incident_id)


async def test_bounded_graph_is_checkpointed_with_append_only_grounded_receipt() -> None:
    settings = _settings()
    database = Database(settings)
    projector = Neo4jPaymentGraphProjector(settings)
    reader = Neo4jEvidenceReader(settings)
    merchant_id = f"merchant-{uuid4()}"
    operator_principal = f"operator-{uuid4().hex}"
    order_id = f"order_{uuid4().hex}"
    payment_id = f"pay_{uuid4().hex}"
    try:
        await projector.initialize_schema()
        incident_id = await _prepare_incident(
            database,
            projector,
            merchant_id=merchant_id,
            order_id=order_id,
            payment_id=payment_id,
        )
        repository = PostgresDiagnosisRepository(database)
        claim = await _claim_incident(
            repository,
            incident_id,
            worker_id="diagnosis-proof-worker",
        )
        seed = await repository.load(claim)
        evidence = await AssembleEvidenceSubgraph(
            reader,
            max_facts=128,
            max_relationships=256,
        ).assemble(seed)

        assert evidence.incident_id == incident_id
        assert evidence.state_generation == seed.state_generation
        assert evidence.state_hash == seed.state_hash
        assert len(evidence.facts) >= 4
        assert "raw_body" not in evidence.model_dump_json()
        assert all(
            edge.source_evidence_id in evidence.evidence_ids
            and edge.target_evidence_id in evidence.evidence_ids
            for edge in evidence.relationships
        )

        cited = next(fact.evidence_id for fact in evidence.facts if fact.kind == "invariant")
        decision = DiagnosisDecision(
            disposition=DiagnosisDisposition.DIAGNOSED,
            summary="The captured payment is not reflected in the referenced order state.",
            root_cause=DiagnosisRootCause.ASYNCHRONOUS_STATE_LAG,
            confidence=0.9,
            cited_evidence_ids=(cited,),
            recommended_action=ActionType.FETCH_AUTHORITATIVE_STATE,
        )
        prompt, prompt_hash = diagnosis_prompt(evidence)
        assert prompt
        receipt = DiagnosisReceipt(
            model="gemini-integration-fixture",
            provider_interaction_id="interaction-fixture",
            prompt_hash=prompt_hash,
            evidence_subgraph=evidence,
            diagnosis=guard_diagnosis(evidence, decision, minimum_confidence=0.7),
            diagnosed_at=datetime.now(UTC),
        )
        await repository.complete(claim, receipt)

        async with database.session_factory() as session:
            work = (
                (
                    await session.execute(
                        select(diagnosis_work).where(diagnosis_work.c.incident_id == incident_id)
                    )
                )
                .mappings()
                .one()
            )
            diagnosis = (
                (
                    await session.execute(
                        select(diagnoses).where(diagnoses.c.incident_id == incident_id)
                    )
                )
                .mappings()
                .one()
            )
            attempt = (
                (
                    await session.execute(
                        select(diagnosis_attempts).where(
                            diagnosis_attempts.c.incident_id == incident_id
                        )
                    )
                )
                .mappings()
                .one()
            )
        assert work["status"] == DiagnosisWorkStatus.COMPLETED.value
        assert work["applied_version"] == work["target_version"] == 1
        assert diagnosis["subgraph_hash"] == evidence.subgraph_hash
        assert diagnosis["disposition"] == DiagnosisDisposition.DIAGNOSED.value
        assert attempt["outcome"] == "completed"

        read_model = PostgresOperatorReadModel(database)
        overview = await read_model.overview(
            principal_id=operator_principal,
            request_id="overview-proof",
        )
        page = await read_model.list_incidents(
            principal_id=operator_principal,
            request_id="list-proof",
            statuses=(IncidentStatus.DETECTED.value,),
            limit=100,
            cursor=None,
        )
        detail = await read_model.get_incident(
            incident_id,
            principal_id=operator_principal,
            request_id="detail-proof",
        )
        assert overview.status_counts[IncidentStatus.DETECTED] >= 1
        assert any(item.incident_id == incident_id for item in page.items)
        assert detail is not None
        assert detail.incident.incident_id == incident_id
        assert detail.latest_diagnosis is not None
        assert detail.latest_diagnosis.evidence_subgraph.subgraph_hash == evidence.subgraph_hash

        async with database.session_factory() as session:
            audit_count = await session.scalar(
                select(func.count())
                .select_from(operator_read_audit)
                .where(operator_read_audit.c.principal_id == operator_principal)
            )
        assert audit_count == 3

        statements: list[tuple[str, dict[str, Any]]] = [
            (
                "UPDATE ledger.diagnoses SET model = 'changed' WHERE incident_id = :incident_id",
                {"incident_id": incident_id},
            ),
            (
                "DELETE FROM ledger.diagnosis_attempts WHERE incident_id = :incident_id",
                {"incident_id": incident_id},
            ),
            (
                "UPDATE ledger.operator_read_audit SET outcome = 'not_found' "
                "WHERE principal_id = :principal_id",
                {"principal_id": operator_principal},
            ),
        ]
        for statement, parameters in statements:
            with pytest.raises(DBAPIError, match="append-only"):
                async with database.transaction() as session:
                    await session.execute(text(statement), parameters)

        async with database.transaction() as session:
            await session.execute(
                update(diagnosis_work)
                .where(diagnosis_work.c.incident_id == incident_id)
                .values(
                    target_version=diagnosis_work.c.target_version + 1,
                    status=DiagnosisWorkStatus.PENDING.value,
                    available_at=func.now(),
                    last_error_code=None,
                )
            )
        permanent = await _claim_incident(
            repository,
            incident_id,
            worker_id="diagnosis-proof-permanent",
        )
        assert await repository.fail(
            permanent,
            error_code="diagnosis_evidence_too_large",
            retryable=False,
            max_failures=5,
            retry_delay_seconds=0,
        )

        async with database.transaction() as session:
            await session.execute(
                update(diagnosis_work)
                .where(diagnosis_work.c.incident_id == incident_id)
                .values(
                    target_version=diagnosis_work.c.target_version + 1,
                    status=DiagnosisWorkStatus.PENDING.value,
                    failure_count=0,
                    available_at=func.now(),
                    last_error_code=None,
                )
            )
        expired = await _claim_incident(
            repository,
            incident_id,
            worker_id="diagnosis-proof-expired",
        )
        async with database.transaction() as session:
            await session.execute(
                update(diagnosis_work)
                .where(diagnosis_work.c.incident_id == incident_id)
                .values(lease_expires_at=func.now() - timedelta(seconds=1))
            )
        replacement = await _claim_incident(
            repository,
            incident_id,
            worker_id="diagnosis-proof-replacement",
        )
        with pytest.raises(DiagnosisLeaseLostError, match="lease"):
            await repository.fail(
                expired,
                error_code="diagnosis_model_timeout",
                retryable=True,
                max_failures=5,
                retry_delay_seconds=0,
            )
        assert not await repository.fail(
            replacement,
            error_code="diagnosis_model_timeout",
            retryable=True,
            max_failures=5,
            retry_delay_seconds=0,
        )

        resolved_at = datetime.now(UTC)
        evaluation_id = uuid4()
        resolution_revision_id = uuid4()
        resolved_lifecycle = seed.incident.model_copy(
            update={
                "status": IncidentStatus.RESOLVED,
                "resolved_at": resolved_at,
                "last_evaluation_id": evaluation_id,
            }
        )
        async with database.transaction() as session:
            await session.execute(
                insert(invariant_evaluations).values(
                    evaluation_id=evaluation_id,
                    merchant_id=merchant_id,
                    correlation_id=order_id,
                    state_generation=seed.state_generation,
                    attempt_number=999,
                    worker_id="diagnosis-resolution-proof",
                    evaluator_version="diagnosis-resolution-proof-v1",
                    outcome=InvariantEvaluationOutcome.COMPLETED.value,
                    error_code=None,
                    state_hash=seed.state_hash,
                    finding_count=0,
                    next_evaluation_at=None,
                    evaluated_at=resolved_at,
                )
            )
            await session.execute(
                update(incidents)
                .where(incidents.c.incident_id == incident_id)
                .values(
                    status=IncidentStatus.RESOLVED.value,
                    resolved_at=resolved_at,
                    last_evaluation_id=evaluation_id,
                )
            )
            await session.execute(
                insert(incident_revisions).values(
                    revision_id=resolution_revision_id,
                    incident_id=incident_id,
                    evaluation_id=evaluation_id,
                    state_generation=seed.state_generation,
                    reason=IncidentRevisionReason.RESOLVED.value,
                    status=IncidentStatus.RESOLVED.value,
                    finding_hash=seed.incident.finding_hash,
                    snapshot=resolved_lifecycle.model_dump(mode="json"),
                )
            )
        async with database.session_factory() as session:
            resolved_work = (
                (
                    await session.execute(
                        select(diagnosis_work).where(diagnosis_work.c.incident_id == incident_id)
                    )
                )
                .mappings()
                .one()
            )
        assert resolved_work["status"] == DiagnosisWorkStatus.COMPLETED.value
        assert resolved_work["applied_version"] == resolved_work["target_version"]
        assert resolved_work["source_revision_id"] == resolution_revision_id
    finally:
        await reader.close()
        await projector.close()
        await database.close()


async def test_action_chain_is_dual_control_idempotent_and_append_only() -> None:
    settings = _settings()
    database = Database(settings)
    projector = Neo4jPaymentGraphProjector(settings)
    reader = Neo4jEvidenceReader(settings)
    merchant_id = f"merchant-{uuid4()}"
    order_id = f"order_{uuid4().hex}"
    payment_id = f"pay_{uuid4().hex}"
    try:
        await projector.initialize_schema()
        incident_id = await _prepare_incident(
            database,
            projector,
            merchant_id=merchant_id,
            order_id=order_id,
            payment_id=payment_id,
            raw_event=_authorized_payment(merchant_id, order_id, payment_id),
        )
        diagnosis_repository = PostgresDiagnosisRepository(database)
        claim = await _claim_incident(
            diagnosis_repository,
            incident_id,
            worker_id="action-proof-diagnostician",
        )
        seed = await diagnosis_repository.load(claim)
        evidence = await AssembleEvidenceSubgraph(
            reader,
            max_facts=128,
            max_relationships=256,
        ).assemble(seed)
        cited = next(fact.evidence_id for fact in evidence.facts if fact.kind == "invariant")
        decision = DiagnosisDecision(
            disposition=DiagnosisDisposition.DIAGNOSED,
            summary="The exact payment authorization remains open beyond the capture window.",
            root_cause=DiagnosisRootCause.CAPTURE_NOT_COMPLETED,
            confidence=0.97,
            cited_evidence_ids=(cited,),
            recommended_action=ActionType.CAPTURE_PAYMENT,
        )
        prompt, prompt_hash = diagnosis_prompt(evidence)
        assert prompt
        await diagnosis_repository.complete(
            claim,
            DiagnosisReceipt(
                model="gemini-action-fixture",
                provider_interaction_id="interaction-action-fixture",
                prompt_hash=prompt_hash,
                evidence_subgraph=evidence,
                diagnosis=guard_diagnosis(evidence, decision, minimum_confidence=0.7),
                diagnosed_at=datetime.now(UTC),
            ),
        )

        gateway = _CaptureGateway(payment_id)
        action_repository = PostgresRecoveryActionRepository(database)
        control = RecoveryActionControlPlane(
            action_repository,
            DeterministicRecoveryPolicy(
                RecoveryPolicyConfig(
                    actions_enabled=True,
                    test_credentials=True,
                    merchant_id=merchant_id,
                    maximum_capture_subunits=20_000,
                    minimum_capture_confidence=0.9,
                )
            ),
            gateway,
            proposal_ttl_seconds=900,
            execution_lease_seconds=30,
        )
        proposal = await control.propose(
            incident_id,
            principal_id="maker",
            request_id="proposal-proof",
        )
        repeated = await control.propose(
            incident_id,
            principal_id="maker",
            request_id="proposal-retry-proof",
        )
        assert repeated.proposal.proposal_id == proposal.proposal.proposal_id
        assert proposal.policy.outcome is PolicyOutcome.REQUIRE_APPROVAL
        assert proposal.proposal.amount == Money(amount_subunits=10_000, currency="INR")

        history = await control.list_for_incident(
            incident_id,
            principal_id="auditor",
            request_id="history-proof",
        )
        assert len(history) == 1

        with pytest.raises(ActionControlError) as maker_decision:
            await control.decide(
                proposal.proposal.proposal_id,
                principal_id="maker",
                request_id="maker-approval-proof",
                decision=ActionApprovalDecision.APPROVED,
                rationale="I cannot approve my own request.",
            )
        assert maker_decision.value.code is ActionControlErrorCode.MAKER_CHECKER_VIOLATION

        approved = await control.decide(
            proposal.proposal.proposal_id,
            principal_id="checker",
            request_id="checker-approval-proof",
            decision=ActionApprovalDecision.APPROVED,
            rationale=(
                "Payment identity, amount, currency, and evidence were independently checked."
            ),
        )
        assert len(approved.approvals) == 1
        executed = await control.execute(
            proposal.proposal.proposal_id,
            principal_id="checker",
            request_id="execution-proof",
        )
        assert executed.execution_status is ActionExecutionStatus.SUCCEEDED
        assert executed.latest_result is not None
        assert executed.latest_result.provider_state is not None
        assert executed.latest_result.provider_state.status is PaymentStatus.CAPTURED
        assert gateway.fetch_count == gateway.capture_count == 1

        idempotent = await control.execute(
            proposal.proposal.proposal_id,
            principal_id="checker",
            request_id="execution-retry-proof",
        )
        assert idempotent.latest_result == executed.latest_result
        assert gateway.fetch_count == gateway.capture_count == 1

        async with database.session_factory() as session:
            counts = {
                "proposals": await session.scalar(
                    select(func.count()).select_from(action_proposals)
                ),
                "policies": await session.scalar(
                    select(func.count()).select_from(action_policy_decisions)
                ),
                "approvals": await session.scalar(
                    select(func.count()).select_from(action_approval_decisions)
                ),
                "claims": await session.scalar(
                    select(func.count()).select_from(action_execution_claims)
                ),
                "mutations": await session.scalar(
                    select(func.count()).select_from(action_mutation_authorizations)
                ),
                "results": await session.scalar(
                    select(func.count()).select_from(action_execution_results)
                ),
                "audits": await session.scalar(
                    select(func.count())
                    .select_from(action_access_audit)
                    .where(action_access_audit.c.resource_id.is_not(None))
                ),
            }
        assert all((count or 0) >= 1 for count in counts.values())

        with pytest.raises(DBAPIError, match="append-only"):
            async with database.transaction() as session:
                await session.execute(
                    update(action_proposals)
                    .where(action_proposals.c.proposal_id == proposal.proposal.proposal_id)
                    .values(rationale="tampered")
                )
        with pytest.raises(DBAPIError, match="append-only"):
            async with database.transaction() as session:
                await session.execute(
                    text(
                        "DELETE FROM ledger.action_execution_results "
                        "WHERE proposal_id = :proposal_id"
                    ),
                    {"proposal_id": proposal.proposal.proposal_id},
                )
    finally:
        await reader.close()
        await projector.close()
        await database.close()
