"""Drain a signed-ingress run through the real PostgreSQL and Neo4j pipeline."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Protocol

from neo4j import AsyncGraphDatabase
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from chakravyuh.application.graph_projection import ProcessGraphProjectionBatch
from chakravyuh.application.invariant_evaluation import ProcessInvariantEvaluationBatch
from chakravyuh.application.journey_reduction import ProcessJourneyReductionBatch
from chakravyuh.application.normalization import ProcessNormalizationBatch
from chakravyuh.config import Settings
from chakravyuh.domain.invariants import (
    DeterministicPaymentInvariantEvaluator,
    InvariantPolicy,
)
from chakravyuh.domain.journeys import TemporalPaymentJourneyReducer
from chakravyuh.infrastructure.database import Database
from chakravyuh.infrastructure.neo4j.projector import Neo4jPaymentGraphProjector
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
from chakravyuh.infrastructure.razorpay.normalizer import RazorpayWebhookNormalizer
from chakravyuh.operations.load_probe import LoadProbeReport

PIPELINE_SCALE_REPORT_VERSION = "full-pipeline-scale-report-v1"


class _BatchResult(Protocol):
    @property
    def claimed(self) -> int: ...

    @property
    def completed(self) -> int: ...

    @property
    def dead_lettered(self) -> int: ...


class _BatchProcessor(Protocol):
    def execute(self) -> Awaitable[_BatchResult]: ...


class StageDrainEvidence(BaseModel):
    """One production stage drained until its durable queue was empty."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: str
    batch_count: int = Field(ge=1)
    claimed: int = Field(ge=0)
    completed: int = Field(ge=0)
    dead_lettered: int = Field(ge=0)
    retried: int = Field(default=0, ge=0)
    lease_lost: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(ge=0)


class PipelineScaleReport(BaseModel):
    """Content-hashed end-to-end proof for one isolated signed-ingress run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: str = PIPELINE_SCALE_REPORT_VERSION
    run_id: str
    ingress_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    merchant_id_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_events: int = Field(ge=1, le=100_000)
    expected_journeys: int = Field(ge=1, le=100_000)
    stage_evidence: tuple[StageDrainEvidence, ...]
    postgres_raw_events: int = Field(ge=0)
    postgres_normalized_events: int = Field(ge=0)
    postgres_journey_states: int = Field(ge=0)
    postgres_journey_event_sum: int = Field(ge=0)
    postgres_invariant_evaluations: int = Field(ge=0)
    postgres_incidents: int = Field(ge=0)
    normalization_status_counts: dict[str, int]
    journey_status_counts: dict[str, int]
    invariant_status_counts: dict[str, int]
    graph_status_counts: dict[str, int]
    graph_attempt_outcome_counts: dict[str, int]
    neo4j_merchants: int = Field(ge=0)
    neo4j_journeys: int = Field(ge=0)
    neo4j_financial_entities: int = Field(ge=0)
    neo4j_money_events: int = Field(ge=0)
    end_to_end_p50_latency_ms: float = Field(ge=0)
    end_to_end_p95_latency_ms: float = Field(ge=0)
    drain_elapsed_seconds: float = Field(ge=0)
    events_per_second: float = Field(ge=0)
    passed: bool
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_report(self) -> PipelineScaleReport:
        if self.passed != _pipeline_passed(self):
            msg = "pipeline-scale pass flag must match its exact drain and graph gates"
            raise ValueError(msg)
        expected_rate = self.expected_events / max(self.drain_elapsed_seconds, 1e-9)
        if not math.isclose(self.events_per_second, expected_rate, rel_tol=1e-12):
            msg = "pipeline-scale throughput does not match events and drain time"
            raise ValueError(msg)
        if _model_hash(self, exclude={"report_sha256"}) != self.report_sha256:
            msg = "pipeline-scale report hash does not match its canonical content"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class PipelineScaleConfig:
    merchant_id: str
    run_id: str
    expected_events: int
    expected_journeys: int
    timeout_seconds: float = 3_600

    def validate(self) -> None:
        if re.fullmatch(r"[A-Za-z0-9_-]{1,255}", self.merchant_id) is None:
            msg = "merchant ID must contain 1..255 URL-safe identifier characters"
            raise ValueError(msg)
        if re.fullmatch(r"[A-Za-z0-9]{1,64}", self.run_id) is None:
            msg = "run ID must contain 1..64 alphanumeric characters"
            raise ValueError(msg)
        if not 1 <= self.expected_events <= 100_000:
            msg = "expected event count must be 1..100000"
            raise ValueError(msg)
        if not 1 <= self.expected_journeys <= self.expected_events:
            msg = "expected journey count must be between one and expected event count"
            raise ValueError(msg)
        if not 1 <= self.timeout_seconds <= 14_400:
            msg = "pipeline timeout must be 1..14400 seconds"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class _PostgresEvidence:
    raw_events: int
    normalized_events: int
    journey_states: int
    journey_event_sum: int
    invariant_evaluations: int
    incidents: int
    normalization_status_counts: dict[str, int]
    journey_status_counts: dict[str, int]
    invariant_status_counts: dict[str, int]
    graph_status_counts: dict[str, int]
    graph_attempt_outcome_counts: dict[str, int]
    latencies: list[float]


async def run_pipeline_scale_proof(
    config: PipelineScaleConfig,
    *,
    ingress: LoadProbeReport,
    settings: Settings,
    progress: Callable[[str, int, int], None] | None = None,
) -> PipelineScaleReport:
    """Drain four production stages and prove their scoped durable effects."""

    config.validate()
    _validate_ingress(config, ingress)
    if settings.environment == "production":
        msg = "pipeline scale proof cannot run in production"
        raise ValueError(msg)
    database = Database(settings)
    projector = Neo4jPaymentGraphProjector(settings)
    started = perf_counter()
    deadline = started + config.timeout_seconds
    try:
        await projector.initialize_schema()
        stages = (
            await _drain_stage(
                "normalization",
                ProcessNormalizationBatch(
                    PostgresNormalizationRepository(database),
                    RazorpayWebhookNormalizer(),
                    worker_id=f"scale-normalize:{config.run_id}",
                    batch_size=500,
                ),
                deadline=deadline,
                progress=progress,
            ),
            await _drain_stage(
                "journey_reduction",
                ProcessJourneyReductionBatch(
                    PostgresJourneyReductionRepository(database),
                    TemporalPaymentJourneyReducer(),
                    worker_id=f"scale-reduce:{config.run_id}",
                    batch_size=500,
                    max_events_per_journey=100_000,
                ),
                deadline=deadline,
                progress=progress,
            ),
            await _drain_stage(
                "invariant_evaluation",
                ProcessInvariantEvaluationBatch(
                    PostgresInvariantEvaluationRepository(database),
                    DeterministicPaymentInvariantEvaluator(
                        InvariantPolicy(
                            captured_order_paid_grace_seconds=(
                                settings.invariant_captured_order_grace_seconds
                            ),
                            authorized_capture_grace_seconds=(
                                settings.invariant_authorized_capture_grace_seconds
                            ),
                            failed_recovery_grace_seconds=(
                                settings.invariant_failed_recovery_grace_seconds
                            ),
                            stale_recovery_link_grace_seconds=(
                                settings.invariant_stale_recovery_link_grace_seconds
                            ),
                        )
                    ),
                    worker_id=f"scale-invariant:{config.run_id}",
                    batch_size=500,
                    max_events_per_journey=100_000,
                ),
                deadline=deadline,
                progress=progress,
            ),
            await _drain_stage(
                "graph_projection",
                ProcessGraphProjectionBatch(
                    PostgresGraphProjectionRepository(database),
                    projector,
                    worker_id=f"scale-project:{config.run_id}",
                    batch_size=100,
                    lease_seconds=3_600,
                    max_failures=5,
                    retry_delay_seconds=0,
                ),
                deadline=deadline,
                progress=progress,
            ),
        )
        elapsed = perf_counter() - started
        postgres = await _postgres_evidence(database, config.merchant_id)
        graph = await _neo4j_evidence(settings, config.merchant_id)
        return _build_report(config, ingress, stages, postgres, graph, elapsed)
    finally:
        await projector.close()
        await database.close()


async def _drain_stage(
    stage: str,
    processor: _BatchProcessor,
    *,
    deadline: float,
    progress: Callable[[str, int, int], None] | None,
) -> StageDrainEvidence:
    started = perf_counter()
    batches = 0
    claimed = 0
    completed = 0
    dead_lettered = 0
    retried = 0
    lease_lost = 0
    while True:
        if perf_counter() >= deadline:
            msg = f"pipeline scale proof timed out while draining {stage}"
            raise TimeoutError(msg)
        result = await processor.execute()
        batches += 1
        claimed += result.claimed
        completed += result.completed
        dead_lettered += result.dead_lettered
        retried += int(getattr(result, "retried", 0))
        lease_lost += int(getattr(result, "lease_lost", 0))
        if progress is not None and (batches == 1 or batches % 20 == 0 or result.claimed == 0):
            progress(stage, batches, completed)
        if result.claimed == 0:
            break
    return StageDrainEvidence(
        stage=stage,
        batch_count=batches,
        claimed=claimed,
        completed=completed,
        dead_lettered=dead_lettered,
        retried=retried,
        lease_lost=lease_lost,
        elapsed_seconds=perf_counter() - started,
    )


async def _postgres_evidence(database: Database, merchant_id: str) -> _PostgresEvidence:
    async with database.session_factory() as session:
        scalars: dict[str, int] = {}
        for name, statement in {
            "raw_events": "SELECT count(*) FROM ledger.webhook_events WHERE merchant_id=:merchant",
            "normalized_events": (
                "SELECT count(*) FROM ledger.normalized_events WHERE merchant_id=:merchant"
            ),
            "journey_states": (
                "SELECT count(*) FROM state.payment_journey_states WHERE merchant_id=:merchant"
            ),
            "journey_event_sum": (
                "SELECT coalesce(sum(event_count),0) FROM state.payment_journey_states "
                "WHERE merchant_id=:merchant"
            ),
            "invariant_evaluations": (
                "SELECT count(*) FROM ledger.invariant_evaluations WHERE merchant_id=:merchant"
            ),
            "incidents": "SELECT count(*) FROM state.incidents WHERE merchant_id=:merchant",
        }.items():
            value = await session.scalar(text(statement), {"merchant": merchant_id})
            scalars[name] = int(value or 0)
        status_queries = {
            "normalization_status_counts": (
                "SELECT work.status, count(*) FROM operations.webhook_normalization_work work "
                "JOIN ledger.webhook_events event ON event.event_id=work.webhook_event_id "
                "WHERE event.merchant_id=:merchant GROUP BY work.status"
            ),
            "journey_status_counts": (
                "SELECT status, count(*) FROM operations.journey_reduction_work "
                "WHERE merchant_id=:merchant GROUP BY status"
            ),
            "invariant_status_counts": (
                "SELECT status, count(*) FROM operations.invariant_evaluation_work "
                "WHERE merchant_id=:merchant GROUP BY status"
            ),
            "graph_status_counts": (
                "SELECT status, count(*) FROM operations.graph_projection_work "
                "WHERE merchant_id=:merchant GROUP BY status"
            ),
            "graph_attempt_outcome_counts": (
                "SELECT outcome, count(*) FROM ledger.graph_projection_attempts "
                "WHERE merchant_id=:merchant GROUP BY outcome"
            ),
        }
        statuses: dict[str, dict[str, int]] = {}
        for name, statement in status_queries.items():
            rows = (await session.execute(text(statement), {"merchant": merchant_id})).all()
            statuses[name] = {str(row[0]): int(row[1]) for row in rows}
        latency_rows = (
            await session.execute(
                text(
                    "WITH ingress AS ("
                    " SELECT normalized.correlation_id, min(raw.recorded_at) AS started_at"
                    " FROM ledger.normalized_events normalized"
                    " JOIN ledger.webhook_events raw"
                    " ON raw.event_id=normalized.source_webhook_event_id"
                    " WHERE normalized.merchant_id=:merchant"
                    " GROUP BY normalized.correlation_id"
                    ") SELECT extract(epoch FROM (work.updated_at-ingress.started_at))*1000"
                    " FROM ingress JOIN operations.graph_projection_work work"
                    " ON work.merchant_id=:merchant"
                    " AND work.correlation_id=ingress.correlation_id"
                    " WHERE work.status='completed'"
                ),
                {"merchant": merchant_id},
            )
        ).scalars()
        latencies = sorted(float(value) for value in latency_rows)
    return _PostgresEvidence(
        raw_events=scalars["raw_events"],
        normalized_events=scalars["normalized_events"],
        journey_states=scalars["journey_states"],
        journey_event_sum=scalars["journey_event_sum"],
        invariant_evaluations=scalars["invariant_evaluations"],
        incidents=scalars["incidents"],
        normalization_status_counts=statuses["normalization_status_counts"],
        journey_status_counts=statuses["journey_status_counts"],
        invariant_status_counts=statuses["invariant_status_counts"],
        graph_status_counts=statuses["graph_status_counts"],
        graph_attempt_outcome_counts=statuses["graph_attempt_outcome_counts"],
        latencies=latencies,
    )


async def _neo4j_evidence(settings: Settings, merchant_id: str) -> dict[str, int]:
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password.get_secret_value()),
        connection_timeout=settings.neo4j_connection_timeout_seconds,
    )
    try:
        async with driver.session(database=settings.neo4j_database) as session:
            result = await session.run(
                """
                MATCH (merchant:Merchant {merchant_id: $merchant_id})-[:OWNS]->(journey)
                OPTIONAL MATCH (journey)-[:HAS_EVENT]->(event:MoneyEvent)
                OPTIONAL MATCH (journey)-[:CONTAINS]->(entity:FinancialEntity)
                RETURN count(DISTINCT merchant) AS merchants,
                       count(DISTINCT journey) AS journeys,
                       count(DISTINCT event) AS events,
                       count(DISTINCT entity) AS entities
                """,
                merchant_id=merchant_id,
            )
            row = await result.single()
        if row is None:
            return {"merchants": 0, "journeys": 0, "events": 0, "entities": 0}
        return {name: int(row[name]) for name in ("merchants", "journeys", "events", "entities")}
    finally:
        await driver.close()


def _build_report(
    config: PipelineScaleConfig,
    ingress: LoadProbeReport,
    stages: tuple[StageDrainEvidence, ...],
    postgres: _PostgresEvidence,
    graph: dict[str, int],
    elapsed: float,
) -> PipelineScaleReport:
    draft = PipelineScaleReport.model_construct(
        report_version=PIPELINE_SCALE_REPORT_VERSION,
        run_id=config.run_id,
        ingress_report_sha256=ingress.report_sha256,
        merchant_id_sha256=hashlib.sha256(config.merchant_id.encode()).hexdigest(),
        expected_events=config.expected_events,
        expected_journeys=config.expected_journeys,
        stage_evidence=stages,
        postgres_raw_events=postgres.raw_events,
        postgres_normalized_events=postgres.normalized_events,
        postgres_journey_states=postgres.journey_states,
        postgres_journey_event_sum=postgres.journey_event_sum,
        postgres_invariant_evaluations=postgres.invariant_evaluations,
        postgres_incidents=postgres.incidents,
        normalization_status_counts=postgres.normalization_status_counts,
        journey_status_counts=postgres.journey_status_counts,
        invariant_status_counts=postgres.invariant_status_counts,
        graph_status_counts=postgres.graph_status_counts,
        graph_attempt_outcome_counts=postgres.graph_attempt_outcome_counts,
        neo4j_merchants=graph["merchants"],
        neo4j_journeys=graph["journeys"],
        neo4j_financial_entities=graph["entities"],
        neo4j_money_events=graph["events"],
        end_to_end_p50_latency_ms=_percentile(postgres.latencies, 0.50),
        end_to_end_p95_latency_ms=_percentile(postgres.latencies, 0.95),
        drain_elapsed_seconds=elapsed,
        events_per_second=config.expected_events / max(elapsed, 1e-9),
        passed=False,
        report_sha256="0" * 64,
    )
    with_pass = draft.model_copy(update={"passed": _pipeline_passed(draft)})
    return PipelineScaleReport.model_validate(
        {
            **with_pass.model_dump(mode="json"),
            "report_sha256": _model_hash(with_pass, exclude={"report_sha256"}),
        }
    )


def _pipeline_passed(report: PipelineScaleReport) -> bool:
    stages = {stage.stage: stage for stage in report.stage_evidence}
    return bool(
        len(report.stage_evidence) == 4
        and set(stages)
        == {"normalization", "journey_reduction", "invariant_evaluation", "graph_projection"}
        and all(
            stage.claimed == stage.completed
            and stage.dead_lettered == 0
            and stage.retried == 0
            and stage.lease_lost == 0
            for stage in report.stage_evidence
        )
        and stages["normalization"].completed == report.expected_events
        and stages["journey_reduction"].completed == report.expected_journeys
        and stages["invariant_evaluation"].completed == report.expected_journeys
        and stages["graph_projection"].completed == report.expected_journeys
        and report.postgres_raw_events == report.expected_events
        and report.postgres_normalized_events == report.expected_events
        and report.postgres_journey_states == report.expected_journeys
        and report.postgres_journey_event_sum == report.expected_events
        and report.postgres_invariant_evaluations == report.expected_journeys
        and report.postgres_incidents == 0
        and report.normalization_status_counts == {"completed": report.expected_events}
        and report.journey_status_counts == {"completed": report.expected_journeys}
        and report.invariant_status_counts == {"completed": report.expected_journeys}
        and report.graph_status_counts == {"completed": report.expected_journeys}
        and report.graph_attempt_outcome_counts == {"completed": report.expected_journeys}
        and report.neo4j_merchants == 1
        and report.neo4j_journeys == report.expected_journeys
        and report.neo4j_financial_entities == report.expected_events
        and report.neo4j_money_events == report.expected_events
    )


def _validate_ingress(config: PipelineScaleConfig, ingress: LoadProbeReport) -> None:
    if not ingress.passed:
        msg = "pipeline proof requires a passing signed-ingress report"
        raise ValueError(msg)
    if (
        ingress.run_id != config.run_id
        or ingress.unique_events != config.expected_events
        or ingress.journey_count != config.expected_journeys
        or ingress.merchant_id_sha256 != hashlib.sha256(config.merchant_id.encode()).hexdigest()
    ):
        msg = "signed-ingress report does not match the requested pipeline run"
        raise ValueError(msg)


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, round((len(values) - 1) * quantile)))
    return values[index]


def _model_hash(model: BaseModel, *, exclude: set[str]) -> str:
    canonical = json.dumps(
        model.model_dump(mode="json", exclude=exclude),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _progress(stage: str, batches: int, completed: int) -> None:
    sys.stderr.write(
        f"pipeline progress: stage={stage}; batches={batches}; completed={completed}\n"
    )
    sys.stderr.flush()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drain one isolated signed-ingress run through PostgreSQL and Neo4j.",
    )
    parser.add_argument("--merchant-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-events", required=True, type=int)
    parser.add_argument("--expected-journeys", required=True, type=int)
    parser.add_argument("--ingress-report", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=3_600)
    parser.add_argument("--acknowledge-isolated-database", action="store_true")
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    if not args.acknowledge_isolated_database:
        sys.stderr.write("pipeline proof rejected: --acknowledge-isolated-database is required\n")
        return 2
    try:
        ingress = LoadProbeReport.model_validate_json(
            args.ingress_report.read_text(encoding="utf-8")
        )
        report = await run_pipeline_scale_proof(
            PipelineScaleConfig(
                merchant_id=args.merchant_id,
                run_id=args.run_id,
                expected_events=args.expected_events,
                expected_journeys=args.expected_journeys,
                timeout_seconds=args.timeout_seconds,
            ),
            ingress=ingress,
            settings=Settings(),
            progress=_progress,
        )
    except (OSError, TimeoutError, ValueError) as failure:
        sys.stderr.write(f"pipeline proof rejected: {failure}\n")
        return 2
    sys.stdout.write(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")
    return 0 if report.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main_async(_parser().parse_args(argv)))


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
