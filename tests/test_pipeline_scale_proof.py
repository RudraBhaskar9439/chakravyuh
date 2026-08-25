"""Full-pipeline scale proof contract tests."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from chakravyuh.config import Settings
from chakravyuh.operations.load_probe import LoadProbeReport
from chakravyuh.operations.load_probe import _model_hash as _load_hash
from chakravyuh.operations.pipeline_scale_proof import (
    PipelineScaleConfig,
    PipelineScaleReport,
    StageDrainEvidence,
    _build_report,
    _PostgresEvidence,
    main,
    run_pipeline_scale_proof,
)


def _ingress() -> LoadProbeReport:
    draft = LoadProbeReport.model_construct(
        report_version="signed-ingress-load-report-v2",
        run_id="scale01",
        target_origin="http://127.0.0.1:8000",
        merchant_id_sha256=hashlib.sha256(b"merchant_phase12f").hexdigest(),
        account_id_sha256="a" * 64,
        unique_events=4,
        journey_count=2,
        duplicate_deliveries=1,
        concurrency=2,
        total_requests=5,
        total_attempts=5,
        transport_failures=0,
        recovered_after_retry=0,
        unrecovered_requests=0,
        accepted_unique=4,
        confirmed_duplicates=1,
        status_counts={"200": 1, "202": 4},
        p50_latency_ms=1,
        p95_latency_ms=2,
        requests_per_second=100,
        passed=True,
        report_sha256="0" * 64,
    )
    return LoadProbeReport.model_validate(
        {
            **draft.model_dump(mode="json"),
            "report_sha256": _load_hash(draft, exclude={"report_sha256"}),
        }
    )


def _stages() -> tuple[StageDrainEvidence, ...]:
    return (
        StageDrainEvidence(
            stage="normalization",
            batch_count=2,
            claimed=4,
            completed=4,
            dead_lettered=0,
            elapsed_seconds=1,
        ),
        StageDrainEvidence(
            stage="journey_reduction",
            batch_count=2,
            claimed=2,
            completed=2,
            dead_lettered=0,
            elapsed_seconds=1,
        ),
        StageDrainEvidence(
            stage="invariant_evaluation",
            batch_count=2,
            claimed=2,
            completed=2,
            dead_lettered=0,
            elapsed_seconds=1,
        ),
        StageDrainEvidence(
            stage="graph_projection",
            batch_count=2,
            claimed=2,
            completed=2,
            dead_lettered=0,
            elapsed_seconds=1,
        ),
    )


def _postgres() -> _PostgresEvidence:
    return _PostgresEvidence(
        raw_events=4,
        normalized_events=4,
        journey_states=2,
        journey_event_sum=4,
        invariant_evaluations=2,
        incidents=0,
        normalization_status_counts={"completed": 4},
        journey_status_counts={"completed": 2},
        invariant_status_counts={"completed": 2},
        graph_status_counts={"completed": 2},
        graph_attempt_outcome_counts={"completed": 2},
        latencies=[10, 20],
    )


def test_pipeline_scale_report_requires_every_exact_durable_effect() -> None:
    report = _build_report(
        PipelineScaleConfig(
            merchant_id="merchant_phase12f",
            run_id="scale01",
            expected_events=4,
            expected_journeys=2,
        ),
        _ingress(),
        _stages(),
        _postgres(),
        {"merchants": 1, "journeys": 2, "events": 4, "entities": 4},
        2,
    )

    assert report.passed
    assert report.events_per_second == 2
    assert report.end_to_end_p50_latency_ms == 10
    assert report.end_to_end_p95_latency_ms == 20
    assert report.report_sha256

    tampered = report.model_dump(mode="json")
    tampered["neo4j_money_events"] = 3
    with pytest.raises(ValidationError, match="pass flag"):
        PipelineScaleReport.model_validate(tampered)

    draft = report.model_copy(update={"events_per_second": 3})
    invalid_rate = draft.model_dump(mode="json")
    invalid_rate["report_sha256"] = _load_hash(draft, exclude={"report_sha256"})
    with pytest.raises(ValidationError, match="throughput"):
        PipelineScaleReport.model_validate(invalid_rate)


@pytest.mark.parametrize(
    "config",
    [
        PipelineScaleConfig("bad/merchant", "scale01", 4, 2),
        PipelineScaleConfig("merchant", "bad-run", 4, 2),
        PipelineScaleConfig("merchant", "scale01", 0, 1),
        PipelineScaleConfig("merchant", "scale01", 4, 5),
        PipelineScaleConfig("merchant", "scale01", 4, 2, timeout_seconds=0),
    ],
)
def test_pipeline_scale_config_rejects_unsafe_bounds(config: PipelineScaleConfig) -> None:
    with pytest.raises(ValueError):
        config.validate()


async def test_pipeline_scale_rejects_production_before_opening_services() -> None:
    with pytest.raises(ValueError, match="production"):
        await run_pipeline_scale_proof(
            PipelineScaleConfig("merchant_phase12f", "scale01", 4, 2),
            ingress=_ingress(),
            settings=Settings(environment="production"),
        )


async def test_pipeline_scale_rejects_mismatched_or_failed_ingress() -> None:
    with pytest.raises(ValueError, match="does not match"):
        await run_pipeline_scale_proof(
            PipelineScaleConfig("merchant_phase12f", "scale02", 4, 2),
            ingress=_ingress(),
            settings=Settings(environment="test"),
        )

    failed = _ingress().model_copy(update={"passed": False})
    with pytest.raises(ValueError, match="passing"):
        await run_pipeline_scale_proof(
            PipelineScaleConfig("merchant_phase12f", "scale01", 4, 2),
            ingress=failed,
            settings=Settings(environment="test"),
        )


def test_pipeline_scale_cli_requires_explicit_isolation_acknowledgement(capsys) -> None:  # type: ignore[no-untyped-def]
    status = main(
        [
            "--merchant-id",
            "merchant_phase12f",
            "--run-id",
            "scale01",
            "--expected-events",
            "4",
            "--expected-journeys",
            "2",
            "--ingress-report",
            "missing.json",
        ]
    )

    assert status == 2
    assert "acknowledge-isolated-database" in capsys.readouterr().err
