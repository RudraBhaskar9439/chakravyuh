"""Precommitted, budgeted live-AI arena tests without network calls."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from chakravyuh.domain.diagnoses import (
    DiagnosisDecision,
    DiagnosisReceipt,
    allowed_actions_for_incident,
    allowed_root_causes_for_incident,
    build_diagnosis_usage,
    diagnosis_prompt,
    guard_diagnosis,
)
from chakravyuh.domain.enums import (
    DiagnosisDisposition,
    EvidenceFactKind,
    IncidentType,
)
from chakravyuh.domain.errors import DiagnosisErrorCode, DiagnosisProcessingError
from chakravyuh.domain.evidence import EvidenceSubgraph
from chakravyuh.domain.recovery_arena import (
    RecoveryArenaContract,
    create_recovery_arena_contract,
)
from chakravyuh.simulation.live_ai_arena import (
    ArenaLiveAiSample,
    ArenaLiveAiSampleManifest,
    build_live_ai_sample,
    create_live_ai_run_contract,
    run_live_ai_arena,
)
from chakravyuh.simulation.recovery_portfolio import (
    RecoveryPortfolio,
    generate_held_out_recovery_portfolio,
)

EXPECTED_SAMPLE_MANIFEST = "7ac31b4b8ca9a5512153bc3bdf7f5e9cc787e7271ddc766d69f0b189f5fe7954"
EXPECTED_RUN_CONTRACT = "05980420795a73c1abec611960d20f8591ad4f05fb263fca26a5a8c8fd083391"


@pytest.fixture(scope="module")
def arena() -> tuple[RecoveryArenaContract, RecoveryPortfolio, ArenaLiveAiSample]:
    contract = create_recovery_arena_contract()
    portfolio = generate_held_out_recovery_portfolio(contract)
    return contract, portfolio, build_live_ai_sample(portfolio, contract)


class _FakeDiagnostician:
    provider = "fake-openrouter"

    def __init__(self, *, fail_every: int | None = None) -> None:
        self.calls = 0
        self.fail_every = fail_every

    async def diagnose(self, evidence: EvidenceSubgraph) -> DiagnosisReceipt:
        self.calls += 1
        if self.fail_every is not None and self.calls % self.fail_every == 0:
            raise DiagnosisProcessingError(DiagnosisErrorCode.MODEL_TIMEOUT, retryable=True)
        invariant_id = next(
            item.evidence_id for item in evidence.facts if item.kind is EvidenceFactKind.INVARIANT
        )
        decision = DiagnosisDecision(
            disposition=DiagnosisDisposition.DIAGNOSED,
            summary="The cited invariant proves a bounded lifecycle inconsistency.",
            root_cause=sorted(
                allowed_root_causes_for_incident(evidence.incident_type),
                key=lambda item: item.value,
            )[0],
            confidence=0.93,
            cited_evidence_ids=(invariant_id,),
            recommended_action=sorted(
                allowed_actions_for_incident(evidence.incident_type),
                key=lambda item: item.value,
            )[0],
        )
        _, prompt_hash = diagnosis_prompt(evidence)
        return DiagnosisReceipt(
            model="openrouter:test-model",
            provider_interaction_id=f"interaction-{self.calls}",
            prompt_hash=prompt_hash,
            evidence_subgraph=evidence,
            diagnosis=guard_diagnosis(evidence, decision, minimum_confidence=0.7),
            provider_usage=build_diagnosis_usage(
                prompt_tokens=200,
                completion_tokens=50,
                total_tokens=250,
                reasoning_tokens=0,
                cached_tokens=0,
                cost_microusd=10,
            ),
            diagnosed_at=evidence.assembled_at,
        )

    async def close(self) -> None:
        return None


def test_live_ai_sample_is_stable_balanced_and_connected(
    arena: tuple[RecoveryArenaContract, RecoveryPortfolio, ArenaLiveAiSample],
) -> None:
    contract, portfolio, sample = arena

    assert sample.manifest.manifest_sha256 == EXPECTED_SAMPLE_MANIFEST
    assert build_live_ai_sample(portfolio, contract).manifest == sample.manifest
    assert sample.manifest.incident_type_counts == {
        "authorized_not_captured": 17,
        "captured_but_order_unpaid": 17,
        "duplicate_active_recovery_links": 16,
        "event_order_corruption": 16,
        "failed_without_recovery": 17,
        "stale_recovery_after_success": 17,
    }
    assert len({item.case_id for item in sample.cases}) == 100
    for item in sample.cases:
        fact_ids = item.evidence_subgraph.evidence_ids
        assert any(fact.kind is EvidenceFactKind.INVARIANT for fact in item.evidence_subgraph.facts)
        assert all(
            relationship.source_evidence_id in fact_ids
            and relationship.target_evidence_id in fact_ids
            for relationship in item.evidence_subgraph.relationships
        )


def test_live_ai_run_contract_commits_budget_and_model(
    arena: tuple[RecoveryArenaContract, RecoveryPortfolio, ArenaLiveAiSample],
) -> None:
    contract, _, sample = arena

    run_contract = create_live_ai_run_contract(sample, contract, requested_model="test-model")

    assert run_contract.run_contract_sha256 == EXPECTED_RUN_CONTRACT
    assert run_contract.call_limit == 100
    assert run_contract.cost_limit_microusd == 1_000_000
    assert run_contract.minimum_provider_success_count == 90
    assert run_contract.max_output_tokens == 512


@pytest.mark.asyncio
async def test_live_ai_run_uses_metered_cost_and_resumes_without_new_calls(
    arena: tuple[RecoveryArenaContract, RecoveryPortfolio, ArenaLiveAiSample],
    tmp_path: Path,
) -> None:
    contract, _, sample = arena
    run_contract = create_live_ai_run_contract(sample, contract, requested_model="test-model")
    checkpoint = tmp_path / "live-ai.jsonl"
    diagnostician = _FakeDiagnostician()

    report, results = await run_live_ai_arena(
        sample,
        run_contract,
        diagnostician,
        checkpoint_path=checkpoint,
    )

    assert report.passed
    assert report.provider_success_count == 100
    assert report.accounted_cost_microusd == 1_000
    assert report.provider_reported_cost_microusd == 1_000
    assert report.total_reserved_cost_microusd > report.accounted_cost_microusd
    assert report.reservation_violation_count == 0
    assert report.effective_model_counts == {"openrouter:test-model": 100}
    assert report.unsafe_effective_decision_count == 0
    assert report.valid_citation_count == 100
    assert report.invariant_citation_count == 100
    assert report.results_root_sha256
    assert len(results) == 100
    assert diagnostician.calls == 100

    resumed = _FakeDiagnostician()
    resumed_report, resumed_results = await run_live_ai_arena(
        sample,
        run_contract,
        resumed,
        checkpoint_path=checkpoint,
    )
    assert resumed.calls == 0
    assert resumed_report == report
    assert resumed_results == results


@pytest.mark.asyncio
async def test_live_ai_failures_are_reserved_and_quality_gate_is_exact(
    arena: tuple[RecoveryArenaContract, RecoveryPortfolio, ArenaLiveAiSample],
    tmp_path: Path,
) -> None:
    contract, _, sample = arena
    run_contract = create_live_ai_run_contract(sample, contract, requested_model="test-model")
    diagnostician = _FakeDiagnostician(fail_every=10)

    report, results = await run_live_ai_arena(
        sample,
        run_contract,
        diagnostician,
        checkpoint_path=tmp_path / "failures.jsonl",
    )

    assert report.passed
    assert report.provider_success_count == 90
    assert report.provider_failure_count == 10
    assert report.accounted_cost_microusd > report.provider_reported_cost_microusd
    assert Counter(item.stable_error_code for item in results if not item.provider_success) == {
        DiagnosisErrorCode.MODEL_TIMEOUT.value: 10
    }


@pytest.mark.asyncio
async def test_live_ai_checkpoint_rejects_duplicates(
    arena: tuple[RecoveryArenaContract, RecoveryPortfolio, ArenaLiveAiSample],
    tmp_path: Path,
) -> None:
    contract, _, sample = arena
    run_contract = create_live_ai_run_contract(sample, contract, requested_model="test-model")
    checkpoint = tmp_path / "tampered.jsonl"
    diagnostician = _FakeDiagnostician()
    _, results = await run_live_ai_arena(
        sample,
        run_contract,
        diagnostician,
        checkpoint_path=checkpoint,
    )
    with checkpoint.open("a", encoding="utf-8") as output:
        output.write(results[0].model_dump_json() + "\n")

    with pytest.raises(ValueError, match="does not match"):
        await run_live_ai_arena(
            sample,
            run_contract,
            _FakeDiagnostician(),
            checkpoint_path=checkpoint,
        )


def test_live_ai_manifest_rejects_tampering(
    arena: tuple[RecoveryArenaContract, RecoveryPortfolio, ArenaLiveAiSample],
) -> None:
    _, _, sample = arena
    body = sample.manifest.model_dump(mode="json")
    body["selection_rule"] = "oracle selected"

    with pytest.raises(ValueError, match="manifest hash"):
        ArenaLiveAiSampleManifest.model_validate(body)


@pytest.mark.parametrize("sample_count", [5, 101])
def test_live_ai_sample_rejects_out_of_contract_sizes(
    arena: tuple[RecoveryArenaContract, RecoveryPortfolio, ArenaLiveAiSample],
    sample_count: int,
) -> None:
    contract, portfolio, _ = arena

    with pytest.raises(ValueError, match="sample size"):
        build_live_ai_sample(portfolio, contract, sample_count=sample_count)


def test_live_ai_sample_contains_every_incident_type(
    arena: tuple[RecoveryArenaContract, RecoveryPortfolio, ArenaLiveAiSample],
) -> None:
    _, _, sample = arena

    assert {item.incident_type for item in sample.cases} == set(IncidentType)
