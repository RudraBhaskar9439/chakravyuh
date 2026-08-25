"""Budgeted live-model evaluation over a precommitted evidence-mesh sample."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chakravyuh.application.ports import StructuredDiagnostician
from chakravyuh.domain.diagnoses import (
    DiagnosisModelUsage,
    allowed_actions_for_incident,
    allowed_root_causes_for_incident,
    diagnosis_prompt,
)
from chakravyuh.domain.enums import (
    ActionType,
    DiagnosisAbstentionReason,
    DiagnosisDisposition,
    DiagnosisRootCause,
    EvidenceFactKind,
    EvidenceRelationshipType,
    IncidentRevisionReason,
    IncidentStatus,
    IncidentType,
)
from chakravyuh.domain.errors import DiagnosisProcessingError
from chakravyuh.domain.evidence import (
    DiagnosisSeed,
    EvidenceSubgraph,
    GraphEvidenceFact,
    GraphEvidenceRelationship,
    GraphEvidenceSnapshot,
    build_evidence_subgraph,
)
from chakravyuh.domain.incidents import IncidentLifecycle
from chakravyuh.domain.invariants import (
    DeterministicPaymentInvariantEvaluator,
    InvariantFinding,
)
from chakravyuh.domain.journeys import journey_state_hash, reduce_payment_journey
from chakravyuh.domain.recovery_arena import RecoveryArenaContract
from chakravyuh.simulation.recovery_portfolio import (
    ArenaEvaluationCase,
    RecoveryPortfolio,
)

LIVE_AI_SAMPLE_VERSION = "recovery-arena-live-ai-sample-v1"
LIVE_AI_RUN_VERSION = "recovery-arena-live-ai-run-v1"
LIVE_AI_REPORT_VERSION = "recovery-arena-live-ai-report-v1"
_SAMPLE_SIZE = 100
_MAX_OUTPUT_TOKENS = 512
_MAX_PROMPT_PRICE_PER_MILLION_USD = 0.5
_MAX_COMPLETION_PRICE_PER_MILLION_USD = 3.0
_MINIMUM_PROVIDER_SUCCESS_COUNT = 90


class ArenaLiveAiSampleCase(BaseModel):
    """One preselected incident and its complete bounded evidence mesh."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    observed_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    incident_type: IncidentType
    affected_entity_id: str
    evidence_subgraph: EvidenceSubgraph
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_case(self) -> ArenaLiveAiSampleCase:
        if self.evidence_subgraph.incident_type is not self.incident_type:
            msg = "live-AI sample incident must match its evidence subgraph"
            raise ValueError(msg)
        if self.evidence_subgraph.affected_entity.entity_id != self.affected_entity_id:
            msg = "live-AI sample affected entity must match its evidence subgraph"
            raise ValueError(msg)
        if _model_hash(self, exclude={"sample_case_sha256"}) != self.sample_case_sha256:
            msg = "live-AI sample case hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ArenaLiveAiSampleManifest(BaseModel):
    """Selection commitment created before any model request is sent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample_version: str = LIVE_AI_SAMPLE_VERSION
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    portfolio_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_count: int = Field(ge=1, le=100)
    selection_rule: str
    incident_type_counts: dict[str, int]
    sample_cases_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_subgraphs_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompts_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> ArenaLiveAiSampleManifest:
        if self.sample_count != sum(self.incident_type_counts.values()):
            msg = "live-AI incident distribution must account for every sample"
            raise ValueError(msg)
        if _model_hash(self, exclude={"manifest_sha256"}) != self.manifest_sha256:
            msg = "live-AI sample manifest hash does not match its canonical content"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class ArenaLiveAiSample:
    manifest: ArenaLiveAiSampleManifest
    cases: tuple[ArenaLiveAiSampleCase, ...]


class ArenaLiveAiRunContract(BaseModel):
    """Hard call, price, output, cost, and quality stops for one resumable run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_version: str = LIVE_AI_RUN_VERSION
    sample_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = "openrouter"
    requested_model: str
    max_output_tokens: int = Field(ge=128, le=2_048)
    max_prompt_price_per_million_usd: float = Field(gt=0)
    max_completion_price_per_million_usd: float = Field(gt=0)
    call_limit: int = Field(ge=1, le=100)
    cost_limit_microusd: int = Field(ge=1)
    minimum_provider_success_count: int = Field(ge=1)
    run_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_run_contract(self) -> ArenaLiveAiRunContract:
        if self.minimum_provider_success_count > self.call_limit:
            msg = "live-AI minimum success count cannot exceed its call limit"
            raise ValueError(msg)
        if _model_hash(self, exclude={"run_contract_sha256"}) != self.run_contract_sha256:
            msg = "live-AI run contract hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ArenaLiveAiCaseResult(BaseModel):
    """Secret-free cached outcome of one model attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_id: str
    sample_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    incident_type: IncidentType
    provider_success: bool
    stable_error_code: str | None = None
    effective_model: str | None = None
    provider_interaction_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latency_ms: float = Field(ge=0)
    reserved_cost_microusd: int = Field(ge=0)
    provider_usage: DiagnosisModelUsage | None = None
    model_disposition: DiagnosisDisposition | None = None
    effective_disposition: DiagnosisDisposition | None = None
    model_root_cause: DiagnosisRootCause | None = None
    model_recommended_action: ActionType | None = None
    model_confidence: float | None = Field(default=None, ge=0, le=1)
    cited_evidence_count: int = Field(ge=0)
    citations_valid: bool
    invariant_cited: bool
    root_cause_allowlisted: bool | None = None
    action_allowlisted: bool | None = None
    guard_reason: DiagnosisAbstentionReason | None = None
    effective_decision_safe: bool
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_result(self) -> ArenaLiveAiCaseResult:
        if self.provider_success != (self.provider_usage is not None):
            msg = "successful live-AI result requires provider-reported usage"
            raise ValueError(msg)
        if self.provider_success and self.stable_error_code is not None:
            msg = "successful live-AI result cannot carry an error"
            raise ValueError(msg)
        if not self.provider_success and not self.stable_error_code:
            msg = "failed live-AI result requires a stable error code"
            raise ValueError(msg)
        if _model_hash(self, exclude={"result_sha256"}) != self.result_sha256:
            msg = "live-AI case result hash does not match its canonical content"
            raise ValueError(msg)
        return self

    @property
    def accounted_cost_microusd(self) -> int:
        if self.provider_usage is None:
            return self.reserved_cost_microusd
        return self.provider_usage.cost_microusd


class ArenaLiveAiReport(BaseModel):
    """Auditable quality and budget result reconstructed from the local checkpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: str = LIVE_AI_REPORT_VERSION
    sample_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_count: int = Field(ge=1)
    attempted_count: int = Field(ge=0)
    provider_success_count: int = Field(ge=0)
    provider_failure_count: int = Field(ge=0)
    model_diagnosed_count: int = Field(ge=0)
    model_abstained_count: int = Field(ge=0)
    effective_diagnosed_count: int = Field(ge=0)
    effective_abstained_count: int = Field(ge=0)
    guard_intervention_count: int = Field(ge=0)
    guard_reason_counts: dict[str, int]
    valid_citation_count: int = Field(ge=0)
    invariant_citation_count: int = Field(ge=0)
    allowlisted_root_cause_count: int = Field(ge=0)
    allowlisted_action_count: int = Field(ge=0)
    unsafe_effective_decision_count: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    cached_tokens: int = Field(ge=0)
    provider_reported_cost_microusd: int = Field(ge=0)
    total_reserved_cost_microusd: int = Field(ge=0)
    accounted_cost_microusd: int = Field(ge=0)
    reservation_violation_count: int = Field(ge=0)
    cost_limit_microusd: int = Field(ge=1)
    call_limit: int = Field(ge=1)
    minimum_provider_success_count: int = Field(ge=1)
    budget_stop_triggered: bool
    p50_latency_ms: float | None = Field(default=None, ge=0)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    incident_type_counts: dict[str, int]
    effective_action_counts: dict[str, int]
    effective_root_cause_counts: dict[str, int]
    effective_model_counts: dict[str, int]
    results_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_report(self) -> ArenaLiveAiReport:
        if self.attempted_count != self.provider_success_count + self.provider_failure_count:
            msg = "live-AI provider outcomes must account for every attempt"
            raise ValueError(msg)
        if self.passed != _live_ai_passed(self):
            msg = "live-AI pass flag must match its budget, safety, and completion gates"
            raise ValueError(msg)
        if _model_hash(self, exclude={"report_sha256"}) != self.report_sha256:
            msg = "live-AI report hash does not match its canonical content"
            raise ValueError(msg)
        return self


def build_live_ai_sample(
    portfolio: RecoveryPortfolio,
    contract: RecoveryArenaContract,
    *,
    sample_count: int = _SAMPLE_SIZE,
) -> ArenaLiveAiSample:
    """Select a balanced sample using observed deterministic findings only."""

    incident_types = tuple(IncidentType)
    if sample_count < len(incident_types) or sample_count > contract.live_model_call_limit:
        msg = "live-AI sample size must cover every incident type within the call limit"
        raise ValueError(msg)
    candidates: dict[IncidentType, list[tuple[ArenaEvaluationCase, InvariantFinding]]] = {
        incident_type: [] for incident_type in incident_types
    }
    evaluator = DeterministicPaymentInvariantEvaluator()
    for case in portfolio.cases:
        state = reduce_payment_journey(list(case.observed.events))
        evaluation = evaluator.evaluate(
            state,
            case.observed.events,
            as_of=case.observed.evaluated_at,
        )
        for finding in evaluation.findings:
            candidates[finding.incident_type].append((case, finding))
    base, remainder = divmod(sample_count, len(incident_types))
    selected: list[ArenaLiveAiSampleCase] = []
    for index, incident_type in enumerate(incident_types):
        target = base + (1 if index < remainder else 0)
        ordered = sorted(
            candidates[incident_type],
            key=lambda item: _canonical_hash(
                {
                    "case_id": item[0].observed.case_id,
                    "incident_type": incident_type.value,
                    "selection_version": LIVE_AI_SAMPLE_VERSION,
                }
            ),
        )
        if len(ordered) < target:
            msg = f"live-AI portfolio has too few {incident_type.value} incidents"
            raise ValueError(msg)
        selected.extend(_sample_case(case, finding) for case, finding in ordered[:target])
    selected_tuple = tuple(sorted(selected, key=lambda item: item.case_id))
    manifest = _sample_manifest(contract, portfolio, selected_tuple)
    return ArenaLiveAiSample(manifest=manifest, cases=selected_tuple)


def create_live_ai_run_contract(
    sample: ArenaLiveAiSample,
    contract: RecoveryArenaContract,
    *,
    requested_model: str,
) -> ArenaLiveAiRunContract:
    draft = ArenaLiveAiRunContract.model_construct(
        run_version=LIVE_AI_RUN_VERSION,
        sample_manifest_sha256=sample.manifest.manifest_sha256,
        provider="openrouter",
        requested_model=requested_model,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
        max_prompt_price_per_million_usd=_MAX_PROMPT_PRICE_PER_MILLION_USD,
        max_completion_price_per_million_usd=_MAX_COMPLETION_PRICE_PER_MILLION_USD,
        call_limit=contract.live_model_call_limit,
        cost_limit_microusd=contract.live_model_cost_limit_microusd,
        minimum_provider_success_count=_MINIMUM_PROVIDER_SUCCESS_COUNT,
        run_contract_sha256="0" * 64,
    )
    return ArenaLiveAiRunContract.model_validate(
        {
            **draft.model_dump(mode="json"),
            "run_contract_sha256": _model_hash(
                draft,
                exclude={"run_contract_sha256"},
            ),
        }
    )


async def run_live_ai_arena(
    sample: ArenaLiveAiSample,
    run_contract: ArenaLiveAiRunContract,
    diagnostician: StructuredDiagnostician,
    *,
    checkpoint_path: Path,
    progress: Callable[[int, int, int], None] | None = None,
) -> tuple[ArenaLiveAiReport, tuple[ArenaLiveAiCaseResult, ...]]:
    """Resume or execute the precommitted sample without exceeding local hard stops."""

    results = _load_checkpoint(checkpoint_path, sample, run_contract)
    by_case = {item.case_id: item for item in results}
    spent = sum(item.accounted_cost_microusd for item in results)
    budget_stop = False
    for case in sample.cases:
        if case.case_id in by_case:
            continue
        if len(results) >= run_contract.call_limit:
            budget_stop = True
            break
        reservation = _request_reservation_microusd(case, run_contract)
        if spent + reservation > run_contract.cost_limit_microusd:
            budget_stop = True
            break
        result = await _diagnose_case(
            case,
            run_contract,
            diagnostician,
            reservation_microusd=reservation,
        )
        _append_checkpoint(checkpoint_path, result)
        results.append(result)
        by_case[result.case_id] = result
        spent += result.accounted_cost_microusd
        if progress is not None:
            progress(len(results), len(sample.cases), spent)
        if spent > run_contract.cost_limit_microusd:
            budget_stop = True
            break
    ordered = tuple(sorted(results, key=lambda item: item.case_id))
    return _live_ai_report(sample, run_contract, ordered, budget_stop), ordered


def _sample_case(
    evaluation_case: ArenaEvaluationCase,
    finding: InvariantFinding,
) -> ArenaLiveAiSampleCase:
    evidence = _evidence_subgraph(evaluation_case, finding)
    _, prompt_hash = diagnosis_prompt(evidence)
    draft = ArenaLiveAiSampleCase.model_construct(
        case_id=evaluation_case.observed.case_id,
        observed_case_sha256=evaluation_case.observed.observed_case_sha256,
        incident_type=finding.incident_type,
        affected_entity_id=finding.affected_entity.entity_id,
        evidence_subgraph=evidence,
        prompt_sha256=prompt_hash,
        sample_case_sha256="0" * 64,
    )
    return ArenaLiveAiSampleCase.model_validate(
        {
            **draft.model_dump(mode="json"),
            "sample_case_sha256": _model_hash(draft, exclude={"sample_case_sha256"}),
        }
    )


def _evidence_subgraph(
    evaluation_case: ArenaEvaluationCase,
    finding: InvariantFinding,
) -> EvidenceSubgraph:
    observed = evaluation_case.observed
    state = reduce_payment_journey(list(observed.events))
    state_hash = journey_state_hash(state)
    identity = f"chakravyuh:live-ai:{observed.case_id}:{finding.incident_key}"
    evaluation_id = uuid5(NAMESPACE_URL, f"{identity}:evaluation")
    incident = IncidentLifecycle(
        incident_id=uuid5(NAMESPACE_URL, f"{identity}:incident"),
        incident_key=finding.incident_key,
        merchant_id=observed.merchant_id,
        correlation_id=observed.correlation_id,
        incident_type=finding.incident_type,
        status=IncidentStatus.DETECTED,
        rule_id=finding.rule_id,
        rule_version=finding.rule_version,
        affected_entity=finding.affected_entity,
        amount_at_risk=finding.amount_at_risk,
        evidence=finding.evidence,
        finding_hash=finding.finding_hash,
        state_generation=1,
        occurrence_count=1,
        first_detected_at=observed.evaluated_at,
        last_detected_at=observed.evaluated_at,
        last_evaluation_id=evaluation_id,
    )
    seed = DiagnosisSeed(
        source_revision_id=uuid5(NAMESPACE_URL, f"{identity}:revision"),
        source_revision_reason=IncidentRevisionReason.DETECTED,
        incident=incident,
        state_generation=1,
        state_hash=state_hash,
    )
    journey_id = f"journey:{observed.correlation_id}"
    entity_ids = {
        (item.entity.entity_type, item.entity.entity_id): (
            f"entity:{item.entity.entity_type.value}:{item.entity.entity_id}"
        )
        for item in state.entities
    }
    facts: list[GraphEvidenceFact] = [
        GraphEvidenceFact(
            evidence_id=journey_id,
            kind=EvidenceFactKind.JOURNEY,
            description="Projected payment journey checkpoint.",
        )
    ]
    relationships: list[GraphEvidenceRelationship] = []
    for entity in state.entities:
        evidence_id = entity_ids[(entity.entity.entity_type, entity.entity.entity_id)]
        facts.append(
            GraphEvidenceFact(
                evidence_id=evidence_id,
                kind=EvidenceFactKind.ENTITY,
                entity=entity.entity,
                provider_status=entity.provider_status,
                effective_payment_status=(
                    None
                    if entity.effective_payment_status is None
                    else entity.effective_payment_status.value
                ),
                amount=entity.amount,
                occurred_at=entity.last_occurred_at,
                description="Current projected financial entity state.",
            )
        )
        relationships.append(
            GraphEvidenceRelationship(
                source_evidence_id=journey_id,
                target_evidence_id=evidence_id,
                relationship_type=EvidenceRelationshipType.CONTAINS,
            )
        )
    unique_events = {item.event_id: item for item in observed.events}
    for event in sorted(unique_events.values(), key=lambda item: item.event_id.hex):
        event_id = f"event:{event.event_id}"
        entity_id = entity_ids[(event.subject.entity_type, event.subject.entity_id)]
        facts.append(
            GraphEvidenceFact(
                evidence_id=event_id,
                kind=EvidenceFactKind.EVENT,
                entity=event.subject,
                event_id=event.event_id,
                event_type=event.event_type,
                provider_status=(
                    event.payload.get("status")
                    if isinstance(event.payload.get("status"), str)
                    else None
                ),
                occurred_at=event.occurred_at,
                description="Normalized provider event evidence.",
            )
        )
        relationships.append(
            GraphEvidenceRelationship(
                source_evidence_id=event_id,
                target_evidence_id=entity_id,
                relationship_type=EvidenceRelationshipType.DESCRIBES,
            )
        )
    relationships.extend(
        GraphEvidenceRelationship(
            source_evidence_id=entity_ids[
                (relationship.source.entity_type, relationship.source.entity_id)
            ],
            target_evidence_id=entity_ids[
                (relationship.target.entity_type, relationship.target.entity_id)
            ],
            relationship_type=EvidenceRelationshipType(relationship.relationship_type.value),
        )
        for relationship in state.relationships
    )
    graph = GraphEvidenceSnapshot(
        merchant_id=observed.merchant_id,
        correlation_id=observed.correlation_id,
        state_generation=1,
        state_hash=state_hash,
        projection_epoch=observed.evaluated_at,
        facts=tuple(facts),
        relationships=tuple(relationships),
    )
    return build_evidence_subgraph(
        seed,
        graph,
        assembled_at=observed.evaluated_at,
        max_facts=128,
        max_relationships=256,
    )


def _sample_manifest(
    contract: RecoveryArenaContract,
    portfolio: RecoveryPortfolio,
    cases: tuple[ArenaLiveAiSampleCase, ...],
) -> ArenaLiveAiSampleManifest:
    counts = Counter(item.incident_type.value for item in cases)
    draft = ArenaLiveAiSampleManifest.model_construct(
        sample_version=LIVE_AI_SAMPLE_VERSION,
        contract_sha256=contract.contract_sha256,
        portfolio_manifest_sha256=portfolio.manifest.manifest_sha256,
        sample_count=len(cases),
        selection_rule=(
            "observed deterministic incident type stratification, then SHA-256 case ordering"
        ),
        incident_type_counts=dict(sorted(counts.items())),
        sample_cases_root_sha256=_merkle_root(sorted(item.sample_case_sha256 for item in cases)),
        evidence_subgraphs_root_sha256=_merkle_root(
            sorted(item.evidence_subgraph.subgraph_hash for item in cases)
        ),
        prompts_root_sha256=_merkle_root(sorted(item.prompt_sha256 for item in cases)),
        manifest_sha256="0" * 64,
    )
    return ArenaLiveAiSampleManifest.model_validate(
        {
            **draft.model_dump(mode="json"),
            "manifest_sha256": _model_hash(draft, exclude={"manifest_sha256"}),
        }
    )


async def _diagnose_case(
    case: ArenaLiveAiSampleCase,
    run_contract: ArenaLiveAiRunContract,
    diagnostician: StructuredDiagnostician,
    *,
    reservation_microusd: int,
) -> ArenaLiveAiCaseResult:
    started = time.perf_counter_ns()
    try:
        receipt = await diagnostician.diagnose(case.evidence_subgraph)
    except DiagnosisProcessingError as failure:
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        return _failed_result(
            case,
            run_contract,
            latency_ms=elapsed,
            reservation_microusd=reservation_microusd,
            error_code=failure.code.value,
        )
    elapsed = (time.perf_counter_ns() - started) / 1_000_000
    usage = receipt.provider_usage
    if usage is None:
        return _failed_result(
            case,
            run_contract,
            latency_ms=elapsed,
            reservation_microusd=reservation_microusd,
            error_code="diagnosis_usage_missing",
        )
    model_decision = receipt.diagnosis.model_decision
    effective = receipt.diagnosis.effective_decision
    cited = set(model_decision.cited_evidence_ids)
    invariant_ids = {
        item.evidence_id
        for item in case.evidence_subgraph.facts
        if item.kind is EvidenceFactKind.INVARIANT
    }
    citations_valid = bool(cited) and cited.issubset(case.evidence_subgraph.evidence_ids)
    invariant_cited = bool(cited & invariant_ids)
    diagnosed = model_decision.disposition is DiagnosisDisposition.DIAGNOSED
    root_allowlisted = (
        model_decision.root_cause in allowed_root_causes_for_incident(case.incident_type)
        if diagnosed
        else None
    )
    action_allowlisted = (
        model_decision.recommended_action in allowed_actions_for_incident(case.incident_type)
        if diagnosed
        else None
    )
    effective_safe = bool(
        effective.disposition is DiagnosisDisposition.ABSTAINED
        or (
            effective.root_cause in allowed_root_causes_for_incident(case.incident_type)
            and effective.recommended_action in allowed_actions_for_incident(case.incident_type)
            and set(effective.cited_evidence_ids).issubset(case.evidence_subgraph.evidence_ids)
            and bool(set(effective.cited_evidence_ids) & invariant_ids)
        )
    )
    draft = ArenaLiveAiCaseResult.model_construct(
        run_contract_sha256=run_contract.run_contract_sha256,
        case_id=case.case_id,
        sample_case_sha256=case.sample_case_sha256,
        incident_type=case.incident_type,
        provider_success=True,
        stable_error_code=None,
        effective_model=receipt.model,
        provider_interaction_sha256=(
            None
            if receipt.provider_interaction_id is None
            else hashlib.sha256(receipt.provider_interaction_id.encode()).hexdigest()
        ),
        latency_ms=elapsed,
        reserved_cost_microusd=reservation_microusd,
        provider_usage=usage,
        model_disposition=model_decision.disposition,
        effective_disposition=effective.disposition,
        model_root_cause=model_decision.root_cause,
        model_recommended_action=model_decision.recommended_action,
        model_confidence=model_decision.confidence,
        cited_evidence_count=len(cited),
        citations_valid=citations_valid,
        invariant_cited=invariant_cited,
        root_cause_allowlisted=root_allowlisted,
        action_allowlisted=action_allowlisted,
        guard_reason=receipt.diagnosis.guard_reason,
        effective_decision_safe=effective_safe,
        result_sha256="0" * 64,
    )
    return ArenaLiveAiCaseResult.model_validate(
        {
            **draft.model_dump(mode="json"),
            "result_sha256": _model_hash(draft, exclude={"result_sha256"}),
        }
    )


def _failed_result(
    case: ArenaLiveAiSampleCase,
    run_contract: ArenaLiveAiRunContract,
    *,
    latency_ms: float,
    reservation_microusd: int,
    error_code: str,
) -> ArenaLiveAiCaseResult:
    draft = ArenaLiveAiCaseResult.model_construct(
        run_contract_sha256=run_contract.run_contract_sha256,
        case_id=case.case_id,
        sample_case_sha256=case.sample_case_sha256,
        incident_type=case.incident_type,
        provider_success=False,
        stable_error_code=error_code,
        latency_ms=latency_ms,
        reserved_cost_microusd=reservation_microusd,
        provider_usage=None,
        cited_evidence_count=0,
        citations_valid=False,
        invariant_cited=False,
        effective_decision_safe=True,
        result_sha256="0" * 64,
    )
    return ArenaLiveAiCaseResult.model_validate(
        {
            **draft.model_dump(mode="json"),
            "result_sha256": _model_hash(draft, exclude={"result_sha256"}),
        }
    )


def _request_reservation_microusd(
    case: ArenaLiveAiSampleCase,
    run_contract: ArenaLiveAiRunContract,
) -> int:
    prompt, _ = diagnosis_prompt(case.evidence_subgraph)
    prompt_token_upper_bound = len(prompt.encode())
    return math.ceil(
        prompt_token_upper_bound * run_contract.max_prompt_price_per_million_usd
        + run_contract.max_output_tokens * run_contract.max_completion_price_per_million_usd
    )


def _load_checkpoint(
    path: Path,
    sample: ArenaLiveAiSample,
    run_contract: ArenaLiveAiRunContract,
) -> list[ArenaLiveAiCaseResult]:
    if not path.exists():
        return []
    sample_cases = {item.case_id: item for item in sample.cases}
    results: list[ArenaLiveAiCaseResult] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            result = ArenaLiveAiCaseResult.model_validate_json(line)
        except ValueError as failure:
            raise ValueError(f"invalid live-AI checkpoint line {line_number}") from failure
        case = sample_cases.get(result.case_id)
        if (
            result.run_contract_sha256 != run_contract.run_contract_sha256
            or case is None
            or result.sample_case_sha256 != case.sample_case_sha256
            or result.case_id in seen
        ):
            msg = "live-AI checkpoint does not match the committed run or sample"
            raise ValueError(msg)
        seen.add(result.case_id)
        results.append(result)
    return results


def _append_checkpoint(path: Path, result: ArenaLiveAiCaseResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(result.model_dump_json())
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def _live_ai_report(
    sample: ArenaLiveAiSample,
    run_contract: ArenaLiveAiRunContract,
    results: tuple[ArenaLiveAiCaseResult, ...],
    budget_stop: bool,
) -> ArenaLiveAiReport:
    successful = tuple(item for item in results if item.provider_success)
    usages = tuple(item.provider_usage for item in successful if item.provider_usage is not None)
    latencies = sorted(item.latency_ms for item in successful)
    model_diagnosed = sum(
        item.model_disposition is DiagnosisDisposition.DIAGNOSED for item in successful
    )
    effective_diagnosed = sum(
        item.effective_disposition is DiagnosisDisposition.DIAGNOSED for item in successful
    )
    effective_actions = Counter(
        item.model_recommended_action.value
        for item in successful
        if item.effective_disposition is DiagnosisDisposition.DIAGNOSED
        and item.model_recommended_action is not None
    )
    effective_causes = Counter(
        item.model_root_cause.value
        for item in successful
        if item.effective_disposition is DiagnosisDisposition.DIAGNOSED
        and item.model_root_cause is not None
    )
    effective_models = Counter(item.effective_model for item in successful if item.effective_model)
    draft = ArenaLiveAiReport.model_construct(
        report_version=LIVE_AI_REPORT_VERSION,
        sample_manifest_sha256=sample.manifest.manifest_sha256,
        run_contract_sha256=run_contract.run_contract_sha256,
        sample_count=len(sample.cases),
        attempted_count=len(results),
        provider_success_count=len(successful),
        provider_failure_count=len(results) - len(successful),
        model_diagnosed_count=model_diagnosed,
        model_abstained_count=len(successful) - model_diagnosed,
        effective_diagnosed_count=effective_diagnosed,
        effective_abstained_count=len(successful) - effective_diagnosed,
        guard_intervention_count=sum(item.guard_reason is not None for item in successful),
        guard_reason_counts=dict(
            sorted(
                Counter(
                    item.guard_reason.value for item in successful if item.guard_reason is not None
                ).items()
            )
        ),
        valid_citation_count=sum(item.citations_valid for item in successful),
        invariant_citation_count=sum(item.invariant_cited for item in successful),
        allowlisted_root_cause_count=sum(
            item.root_cause_allowlisted is True for item in successful
        ),
        allowlisted_action_count=sum(item.action_allowlisted is True for item in successful),
        unsafe_effective_decision_count=sum(
            not item.effective_decision_safe for item in successful
        ),
        prompt_tokens=sum(item.prompt_tokens for item in usages),
        completion_tokens=sum(item.completion_tokens for item in usages),
        reasoning_tokens=sum(item.reasoning_tokens for item in usages),
        cached_tokens=sum(item.cached_tokens for item in usages),
        provider_reported_cost_microusd=sum(item.cost_microusd for item in usages),
        total_reserved_cost_microusd=sum(item.reserved_cost_microusd for item in results),
        accounted_cost_microusd=sum(item.accounted_cost_microusd for item in results),
        reservation_violation_count=sum(
            item.provider_usage is not None
            and item.provider_usage.cost_microusd > item.reserved_cost_microusd
            for item in results
        ),
        cost_limit_microusd=run_contract.cost_limit_microusd,
        call_limit=run_contract.call_limit,
        minimum_provider_success_count=run_contract.minimum_provider_success_count,
        budget_stop_triggered=budget_stop,
        p50_latency_ms=None if not latencies else median(latencies),
        p95_latency_ms=None if not latencies else _percentile(latencies, 0.95),
        incident_type_counts=dict(
            sorted(Counter(item.incident_type.value for item in results).items())
        ),
        effective_action_counts=dict(sorted(effective_actions.items())),
        effective_root_cause_counts=dict(sorted(effective_causes.items())),
        effective_model_counts=dict(sorted(effective_models.items())),
        results_root_sha256=(
            hashlib.sha256(b"chakravyuh:live-ai:no-results").hexdigest()
            if not results
            else _merkle_root(sorted(item.result_sha256 for item in results))
        ),
        passed=False,
        report_sha256="0" * 64,
    )
    passed = _live_ai_passed(draft)
    with_pass = draft.model_copy(update={"passed": passed})
    return ArenaLiveAiReport.model_validate(
        {
            **with_pass.model_dump(mode="json"),
            "report_sha256": _model_hash(with_pass, exclude={"report_sha256"}),
        }
    )


def _live_ai_passed(report: ArenaLiveAiReport) -> bool:
    return bool(
        report.attempted_count == report.sample_count
        and report.attempted_count <= report.call_limit
        and report.provider_success_count >= report.minimum_provider_success_count
        and report.accounted_cost_microusd <= report.cost_limit_microusd
        and report.reservation_violation_count == 0
        and report.unsafe_effective_decision_count == 0
    )


def _percentile(values: Sequence[float], quantile: float) -> float:
    index = max(0, min(len(values) - 1, math.ceil(len(values) * quantile) - 1))
    return values[index]


def _model_hash(model: BaseModel, *, exclude: set[str]) -> str:
    return _canonical_hash(model.model_dump(mode="json", exclude=exclude))


def _merkle_root(hashes: Sequence[str]) -> str:
    if not hashes:
        msg = "live-AI proof root requires at least one hash"
        raise ValueError(msg)
    layer = [bytes.fromhex(value) for value in hashes]
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [
            hashlib.sha256(layer[index] + layer[index + 1]).digest()
            for index in range(0, len(layer), 2)
        ]
    return layer[0].hex()


def _canonical_hash(value: object) -> str:
    body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()
