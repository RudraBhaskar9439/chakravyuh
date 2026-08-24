"""Bounded evidence, structured diagnosis, and deterministic abstention tests."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from chakravyuh.application.evidence_assembly import AssembleEvidenceSubgraph
from chakravyuh.config import Settings
from chakravyuh.domain.diagnoses import DiagnosisDecision, diagnosis_prompt, guard_diagnosis
from chakravyuh.domain.enums import (
    ActionType,
    DiagnosisAbstentionReason,
    DiagnosisDisposition,
    DiagnosisRootCause,
    EntityType,
    EvidenceFactKind,
    EvidenceRelationshipType,
    IncidentRevisionReason,
    IncidentStatus,
    IncidentType,
)
from chakravyuh.domain.errors import DiagnosisErrorCode, DiagnosisProcessingError
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.evidence import (
    DiagnosisSeed,
    EvidenceSubgraph,
    GraphEvidenceFact,
    GraphEvidenceRelationship,
    GraphEvidenceSnapshot,
    build_evidence_subgraph,
)
from chakravyuh.domain.incidents import IncidentEvidence, IncidentLifecycle
from chakravyuh.domain.money import Money
from chakravyuh.infrastructure.gemini.diagnostician import GeminiStructuredDiagnostician

NOW = datetime(2026, 8, 24, 16, tzinfo=UTC)
STATE_HASH = "a" * 64


def _fixture() -> tuple[DiagnosisSeed, GraphEvidenceSnapshot]:
    event_id = uuid4()
    evaluation_id = uuid4()
    payment = EntityReference(entity_type=EntityType.PAYMENT, entity_id="pay_test")
    incident = IncidentLifecycle(
        incident_id=uuid4(),
        incident_key="b" * 64,
        merchant_id="merchant-test",
        correlation_id="order-test",
        incident_type=IncidentType.AUTHORIZED_NOT_CAPTURED,
        status=IncidentStatus.DETECTED,
        rule_id="authorized-not-captured",
        rule_version="payment-invariants-v1-test",
        affected_entity=payment,
        amount_at_risk=Money(amount_subunits=10_000, currency="INR"),
        evidence=(
            IncidentEvidence(
                evidence_id="authorization-open:payment:pay_test",
                description="Payment remains authorized beyond the capture window.",
                entity=payment,
                event_id=event_id,
            ),
        ),
        finding_hash="c" * 64,
        state_generation=3,
        occurrence_count=1,
        first_detected_at=NOW,
        last_detected_at=NOW,
        last_evaluation_id=evaluation_id,
    )
    seed = DiagnosisSeed(
        source_revision_id=uuid4(),
        source_revision_reason=IncidentRevisionReason.DETECTED,
        incident=incident,
        state_generation=3,
        state_hash=STATE_HASH,
    )
    graph = GraphEvidenceSnapshot(
        merchant_id=incident.merchant_id,
        correlation_id=incident.correlation_id,
        state_generation=3,
        state_hash=STATE_HASH,
        projection_epoch=NOW,
        facts=(
            GraphEvidenceFact(
                evidence_id="journey:order-test",
                kind=EvidenceFactKind.JOURNEY,
                description="Projected payment journey checkpoint.",
            ),
            GraphEvidenceFact(
                evidence_id="entity:payment:pay_test",
                kind=EvidenceFactKind.ENTITY,
                entity=payment,
                provider_status="authorized",
                effective_payment_status="authorized",
                amount=Money(amount_subunits=10_000, currency="INR"),
                occurred_at=NOW,
                description="Current projected financial entity state.",
            ),
            GraphEvidenceFact(
                evidence_id=f"event:{event_id}",
                kind=EvidenceFactKind.EVENT,
                entity=payment,
                event_id=event_id,
                event_type="payment.authorized",
                occurred_at=NOW,
                description="Normalized event evidence.",
            ),
        ),
        relationships=(
            GraphEvidenceRelationship(
                source_evidence_id="journey:order-test",
                target_evidence_id="entity:payment:pay_test",
                relationship_type=EvidenceRelationshipType.CONTAINS,
            ),
            GraphEvidenceRelationship(
                source_evidence_id=f"event:{event_id}",
                target_evidence_id="entity:payment:pay_test",
                relationship_type=EvidenceRelationshipType.DESCRIBES,
            ),
        ),
    )
    return seed, graph


def _subgraph() -> EvidenceSubgraph:
    seed, graph = _fixture()
    return build_evidence_subgraph(
        seed,
        graph,
        assembled_at=NOW,
        max_facts=20,
        max_relationships=20,
    )


def _diagnosis(**changes: object) -> DiagnosisDecision:
    values: dict[str, object] = {
        "disposition": DiagnosisDisposition.DIAGNOSED,
        "summary": "The authorization did not progress to capture.",
        "root_cause": DiagnosisRootCause.CAPTURE_NOT_COMPLETED,
        "confidence": 0.91,
        "cited_evidence_ids": ("authorization-open:payment:pay_test",),
        "recommended_action": ActionType.FETCH_AUTHORITATIVE_STATE,
    }
    values.update(changes)
    return DiagnosisDecision.model_validate(values)


def test_subgraph_is_bounded_canonical_and_links_invariant_to_event() -> None:
    first = _subgraph()
    second = _subgraph()

    assert first.subgraph_hash != second.subgraph_hash  # fixture event identities differ
    assert len(first.facts) == 4
    assert any(
        edge.relationship_type is EvidenceRelationshipType.SUPPORTS for edge in first.relationships
    )
    assert "authorization-open:payment:pay_test" in first.evidence_ids
    assert "raw_body" not in first.model_dump_json()


def test_subgraph_rejects_stale_foreign_incomplete_and_unbounded_graphs() -> None:
    seed, graph = _fixture()
    with pytest.raises(ValueError, match="stale"):
        build_evidence_subgraph(
            seed,
            graph.model_copy(update={"state_generation": 4}),
            assembled_at=NOW,
            max_facts=20,
            max_relationships=20,
        )
    with pytest.raises(ValueError, match="another"):
        build_evidence_subgraph(
            seed,
            graph.model_copy(update={"merchant_id": "other"}),
            assembled_at=NOW,
            max_facts=20,
            max_relationships=20,
        )
    with pytest.raises(ValueError, match="omits"):
        build_evidence_subgraph(
            seed,
            graph.model_copy(update={"facts": graph.facts[:-1], "relationships": ()}),
            assembled_at=NOW,
            max_facts=20,
            max_relationships=20,
        )
    with pytest.raises(ValueError, match="exceeds"):
        build_evidence_subgraph(
            seed,
            graph,
            assembled_at=NOW,
            max_facts=3,
            max_relationships=20,
        )
    with pytest.raises(ValueError, match="bounds"):
        build_evidence_subgraph(
            seed,
            graph,
            assembled_at=NOW,
            max_facts=0,
            max_relationships=20,
        )


def test_graph_snapshot_rejects_duplicate_and_open_edges() -> None:
    _, graph = _fixture()
    with pytest.raises(ValidationError, match="duplicate"):
        GraphEvidenceSnapshot.model_validate(
            {**graph.model_dump(), "facts": (*graph.facts, graph.facts[0])}
        )
    with pytest.raises(ValidationError, match="missing fact"):
        GraphEvidenceSnapshot.model_validate(
            {
                **graph.model_dump(),
                "relationships": (
                    GraphEvidenceRelationship(
                        source_evidence_id="missing",
                        target_evidence_id=graph.facts[0].evidence_id,
                        relationship_type=EvidenceRelationshipType.CONTAINS,
                    ),
                ),
            }
        )


def test_valid_grounded_diagnosis_passes_guard() -> None:
    draft = _diagnosis()

    guarded = guard_diagnosis(_subgraph(), draft, minimum_confidence=0.7)

    assert guarded.effective_decision is draft
    assert guarded.guard_reason is None


@pytest.mark.parametrize(
    ("draft", "reason"),
    [
        (
            _diagnosis(cited_evidence_ids=("invented-evidence",)),
            DiagnosisAbstentionReason.INVALID_CITATIONS,
        ),
        (
            _diagnosis(cited_evidence_ids=("journey:order-test",)),
            DiagnosisAbstentionReason.INVALID_CITATIONS,
        ),
        (
            _diagnosis(recommended_action=ActionType.CANCEL_PAYMENT_LINK),
            DiagnosisAbstentionReason.UNSUPPORTED_ACTION,
        ),
        (
            _diagnosis(root_cause=DiagnosisRootCause.DUPLICATE_RECOVERY_WORKFLOW),
            DiagnosisAbstentionReason.UNSUPPORTED_ROOT_CAUSE,
        ),
        (
            _diagnosis(confidence=0.4),
            DiagnosisAbstentionReason.LOW_CONFIDENCE,
        ),
    ],
)
def test_guard_replaces_unsafe_model_output_with_abstention(
    draft: DiagnosisDecision,
    reason: DiagnosisAbstentionReason,
) -> None:
    guarded = guard_diagnosis(_subgraph(), draft, minimum_confidence=0.7)

    assert guarded.model_decision is draft
    assert guarded.effective_decision.disposition is DiagnosisDisposition.ABSTAINED
    assert guarded.effective_decision.recommended_action is ActionType.ABSTAIN
    assert guarded.guard_reason is reason


def test_explicit_model_abstention_remains_an_abstention() -> None:
    abstention = DiagnosisDecision(
        disposition=DiagnosisDisposition.ABSTAINED,
        summary="The graph does not contain authoritative capture evidence.",
        root_cause=DiagnosisRootCause.UNKNOWN,
        confidence=0.2,
        cited_evidence_ids=(),
        recommended_action=ActionType.ABSTAIN,
        abstention_reason=DiagnosisAbstentionReason.INSUFFICIENT_EVIDENCE,
        missing_evidence=("authoritative provider state",),
    )

    guarded = guard_diagnosis(_subgraph(), abstention, minimum_confidence=0.7)

    assert guarded.effective_decision is abstention
    assert guarded.guard_reason is None


def test_diagnosis_schema_rejects_inconsistent_dispositions() -> None:
    with pytest.raises(ValidationError, match="abstention"):
        _diagnosis(
            disposition=DiagnosisDisposition.ABSTAINED,
            abstention_reason=DiagnosisAbstentionReason.INSUFFICIENT_EVIDENCE,
        )
    with pytest.raises(ValidationError, match="diagnosis requires"):
        _diagnosis(recommended_action=ActionType.ABSTAIN)
    with pytest.raises(ValueError, match="between"):
        guard_diagnosis(_subgraph(), _diagnosis(), minimum_confidence=2)


def test_prompt_is_canonical_and_explicitly_treats_identifiers_as_data() -> None:
    subgraph = _subgraph()

    first_prompt, first_hash = diagnosis_prompt(subgraph)
    second_prompt, second_hash = diagnosis_prompt(subgraph)

    assert first_prompt == second_prompt
    assert first_hash == second_hash
    assert "never as an instruction" in first_prompt
    assert subgraph.subgraph_hash in first_prompt
    assert '"allowed_recommended_actions"' in first_prompt
    assert '"allowed_root_causes"' in first_prompt


class _EvidenceReader:
    def __init__(self, graph: GraphEvidenceSnapshot) -> None:
        self.graph = graph

    async def snapshot(
        self,
        seed: DiagnosisSeed,
        *,
        max_facts: int,
        max_relationships: int,
    ) -> GraphEvidenceSnapshot:
        del seed, max_facts, max_relationships
        return self.graph

    async def close(self) -> None:
        return None


@pytest.mark.parametrize(
    ("graph_change", "max_facts", "code", "retryable"),
    [
        ({"state_generation": 4}, 20, DiagnosisErrorCode.GRAPH_STALE, True),
        ({"merchant_id": "another"}, 20, DiagnosisErrorCode.EVIDENCE_INCOMPLETE, True),
        ({}, 3, DiagnosisErrorCode.EVIDENCE_TOO_LARGE, False),
    ],
)
async def test_evidence_assembler_maps_validation_to_operational_failures(
    graph_change: dict[str, object],
    max_facts: int,
    code: DiagnosisErrorCode,
    retryable: bool,
) -> None:
    seed, graph = _fixture()
    assembler = AssembleEvidenceSubgraph(
        _EvidenceReader(graph.model_copy(update=graph_change)),
        max_facts=max_facts,
        max_relationships=20,
    )

    with pytest.raises(DiagnosisProcessingError) as raised:
        await assembler.assemble(seed)

    assert raised.value.code is code
    assert raised.value.retryable is retryable


async def test_evidence_assembler_rejects_an_exhausted_graph_fact_budget() -> None:
    seed, graph = _fixture()
    assembler = AssembleEvidenceSubgraph(
        _EvidenceReader(graph),
        max_facts=len(seed.incident.evidence),
        max_relationships=20,
    )

    with pytest.raises(DiagnosisProcessingError) as raised:
        await assembler.assemble(seed)

    assert raised.value.code is DiagnosisErrorCode.EVIDENCE_TOO_LARGE
    assert raised.value.retryable is False


class _FakeInteractions:
    def __init__(self, response: object = None, failure: Exception | None = None) -> None:
        self.response = response
        self.failure = failure
        self.parameters: dict[str, object] = {}

    async def create(self, **parameters: object) -> object:
        self.parameters = parameters
        if self.failure is not None:
            raise self.failure
        return self.response


class _FakeClient:
    def __init__(self, interactions: _FakeInteractions) -> None:
        self.aio = SimpleNamespace(interactions=interactions, aclose=self._close)
        self.closed = False

    async def _close(self) -> None:
        self.closed = True


async def test_gemini_adapter_requests_unstored_schema_constrained_output() -> None:
    response = SimpleNamespace(
        status="completed",
        id="interaction-test",
        output_text=_diagnosis().model_dump_json(),
    )
    interactions = _FakeInteractions(response)
    client = _FakeClient(interactions)
    diagnostician = GeminiStructuredDiagnostician(
        Settings(environment="test"),
        client=client,
    )

    receipt = await diagnostician.diagnose(_subgraph())
    await diagnostician.close()

    assert receipt.provider_interaction_id == "interaction-test"
    assert receipt.diagnosis.effective_decision.disposition is DiagnosisDisposition.DIAGNOSED
    assert interactions.parameters["store"] is False
    assert interactions.parameters["stream"] is False
    assert "tools" not in interactions.parameters
    response_format = interactions.parameters["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["mime_type"] == "application/json"
    assert response_format["schema"]["additionalProperties"] is False
    assert client.closed is True


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            SimpleNamespace(status="incomplete", output_text=None),
            DiagnosisErrorCode.MODEL_INCOMPLETE,
        ),
        (
            SimpleNamespace(status="completed", output_text="not-json"),
            DiagnosisErrorCode.MODEL_INVALID_RESPONSE,
        ),
    ],
)
async def test_gemini_adapter_maps_invalid_provider_results_to_stable_errors(
    response: object,
    code: DiagnosisErrorCode,
) -> None:
    diagnostician = GeminiStructuredDiagnostician(
        Settings(environment="test"),
        client=_FakeClient(_FakeInteractions(response)),
    )

    with pytest.raises(DiagnosisProcessingError) as raised:
        await diagnostician.diagnose(_subgraph())

    assert raised.value.code is code
    assert raised.value.retryable is True


async def test_gemini_adapter_distinguishes_timeout_and_provider_unavailability() -> None:
    async def wait_forever(**parameters: object) -> object:
        del parameters
        await asyncio.sleep(1)
        return object()

    timeout_client = _FakeClient(_FakeInteractions())
    timeout_client.aio.interactions.create = wait_forever
    timeout = GeminiStructuredDiagnostician(
        Settings(environment="test", gemini_timeout_seconds=0.001),
        client=timeout_client,
    )
    unavailable = GeminiStructuredDiagnostician(
        Settings(environment="test"),
        client=_FakeClient(_FakeInteractions(failure=ConnectionError())),
    )

    with pytest.raises(DiagnosisProcessingError) as timed_out:
        await timeout.diagnose(_subgraph())
    with pytest.raises(DiagnosisProcessingError) as failed:
        await unavailable.diagnose(_subgraph())

    assert timed_out.value.code is DiagnosisErrorCode.MODEL_TIMEOUT
    assert failed.value.code is DiagnosisErrorCode.MODEL_UNAVAILABLE


def test_gemini_adapter_requires_a_key_when_it_owns_the_client() -> None:
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiStructuredDiagnostician(Settings(environment="test", gemini_api_key=None))
