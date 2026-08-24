"""SQLAlchemy table metadata mirrored by reviewed Alembic migrations."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from chakravyuh.domain.webhooks import MAX_STORED_WEBHOOK_BYTES

metadata = MetaData(schema="ledger")

webhook_events = Table(
    "webhook_events",
    metadata,
    Column("event_id", Uuid(as_uuid=True), primary_key=True),
    Column("merchant_id", String(255), nullable=False),
    Column("source", String(64), nullable=False),
    Column("source_event_id", String(255), nullable=False),
    Column("event_type", String(255), nullable=False),
    Column("account_id", String(255), nullable=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column(
        "recorded_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("payload", JSONB, nullable=False),
    Column("raw_body", LargeBinary, nullable=False),
    Column("body_sha256", String(64), nullable=False),
    UniqueConstraint(
        "merchant_id",
        "source",
        "source_event_id",
        name="uq_webhook_events_provider_identity",
    ),
    CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_webhook_payload_object"),
    CheckConstraint(
        f"octet_length(raw_body) BETWEEN 1 AND {MAX_STORED_WEBHOOK_BYTES}",
        name="ck_webhook_body_size",
    ),
    CheckConstraint("body_sha256 ~ '^[0-9a-f]{64}$'", name="ck_webhook_body_sha256"),
)

Index(
    "ix_webhook_events_merchant_observed",
    webhook_events.c.merchant_id,
    webhook_events.c.observed_at,
    webhook_events.c.event_id,
)

normalized_events = Table(
    "normalized_events",
    metadata,
    Column("event_id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "source_webhook_event_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.webhook_events.event_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("schema_version", Integer, nullable=False),
    Column("merchant_id", String(255), nullable=False),
    Column("source", String(64), nullable=False),
    Column("source_event_id", String(255), nullable=False),
    Column("event_type", String(255), nullable=False),
    Column("subject_type", String(64), nullable=False),
    Column("subject_id", String(255), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column(
        "recorded_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("correlation_id", String(255), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("normalizer_version", String(64), nullable=False),
    UniqueConstraint(
        "merchant_id",
        "source",
        "source_event_id",
        name="uq_normalized_events_provider_identity",
    ),
    CheckConstraint("schema_version >= 1", name="ck_normalized_schema_version"),
    CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_normalized_payload_object"),
    CheckConstraint(
        "observed_at >= occurred_at",
        name="ck_normalized_observation_order",
    ),
)

Index(
    "ix_normalized_events_merchant_occurred",
    normalized_events.c.merchant_id,
    normalized_events.c.occurred_at,
    normalized_events.c.event_id,
)
Index(
    "ix_normalized_events_correlation",
    normalized_events.c.merchant_id,
    normalized_events.c.correlation_id,
    normalized_events.c.occurred_at,
)

normalization_work = Table(
    "webhook_normalization_work",
    metadata,
    Column(
        "webhook_event_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.webhook_events.event_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("status", String(32), nullable=False, server_default="pending"),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column(
        "available_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("last_error_code", String(64), nullable=True),
    Column(
        "normalized_event_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.normalized_events.event_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint(
        "status IN ('pending', 'completed', 'dead_letter')",
        name="ck_normalization_work_status",
    ),
    CheckConstraint("attempt_count >= 0", name="ck_normalization_work_attempt_count"),
    CheckConstraint(
        "(status = 'completed' AND normalized_event_id IS NOT NULL "
        "AND last_error_code IS NULL) OR "
        "(status = 'dead_letter' AND normalized_event_id IS NULL "
        "AND last_error_code IS NOT NULL) OR "
        "(status = 'pending' AND normalized_event_id IS NULL "
        "AND last_error_code IS NULL)",
        name="ck_normalization_work_consistent_outcome",
    ),
    schema="operations",
)

Index(
    "ix_normalization_work_claim",
    normalization_work.c.status,
    normalization_work.c.available_at,
    normalization_work.c.webhook_event_id,
)

normalization_attempts = Table(
    "normalization_attempts",
    metadata,
    Column("attempt_id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "webhook_event_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.webhook_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("attempt_number", Integer, nullable=False),
    Column("worker_id", String(255), nullable=False),
    Column("outcome", String(32), nullable=False),
    Column("error_code", String(64), nullable=True),
    Column(
        "normalized_event_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.normalized_events.event_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("normalizer_version", String(64), nullable=False),
    Column(
        "attempted_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    UniqueConstraint(
        "webhook_event_id",
        "attempt_number",
        name="uq_normalization_attempt_number",
    ),
    CheckConstraint("attempt_number >= 1", name="ck_normalization_attempt_number"),
    CheckConstraint(
        "outcome IN ('completed', 'dead_letter')",
        name="ck_normalization_attempt_outcome",
    ),
    CheckConstraint(
        "(outcome = 'completed' AND normalized_event_id IS NOT NULL "
        "AND error_code IS NULL) OR "
        "(outcome = 'dead_letter' AND normalized_event_id IS NULL "
        "AND error_code IS NOT NULL)",
        name="ck_normalization_attempt_consistent_outcome",
    ),
)

normalization_replays = Table(
    "normalization_replays",
    metadata,
    Column("replay_id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "webhook_event_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.webhook_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("requested_by", String(255), nullable=False),
    Column("reason", Text, nullable=False),
    Column(
        "requested_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("length(trim(requested_by)) >= 1", name="ck_replay_requested_by"),
    CheckConstraint("length(trim(reason)) >= 1", name="ck_replay_reason"),
)

journey_reduction_work = Table(
    "journey_reduction_work",
    metadata,
    Column("merchant_id", String(255), primary_key=True),
    Column("correlation_id", String(255), primary_key=True),
    Column("generation", Integer, nullable=False),
    Column("applied_generation", Integer, nullable=False, server_default="0"),
    Column("status", String(32), nullable=False, server_default="pending"),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column(
        "available_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("last_error_code", String(64), nullable=True),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("generation >= 1", name="ck_journey_work_generation"),
    CheckConstraint(
        "applied_generation BETWEEN 0 AND generation",
        name="ck_journey_work_applied_generation",
    ),
    CheckConstraint("attempt_count >= 0", name="ck_journey_work_attempt_count"),
    CheckConstraint(
        "status IN ('pending', 'completed', 'dead_letter')",
        name="ck_journey_work_status",
    ),
    CheckConstraint(
        "(status = 'pending' AND applied_generation < generation "
        "AND last_error_code IS NULL) OR "
        "(status = 'completed' AND applied_generation = generation "
        "AND last_error_code IS NULL) OR "
        "(status = 'dead_letter' AND applied_generation < generation "
        "AND last_error_code IS NOT NULL)",
        name="ck_journey_work_consistent_outcome",
    ),
    schema="operations",
)

Index(
    "ix_journey_reduction_work_claim",
    journey_reduction_work.c.status,
    journey_reduction_work.c.available_at,
    journey_reduction_work.c.merchant_id,
    journey_reduction_work.c.correlation_id,
)

payment_journey_states = Table(
    "payment_journey_states",
    metadata,
    Column("merchant_id", String(255), primary_key=True),
    Column("correlation_id", String(255), primary_key=True),
    Column("generation", Integer, nullable=False),
    Column("event_count", Integer, nullable=False),
    Column("reducer_version", String(64), nullable=False),
    Column("state_hash", String(64), nullable=False),
    Column("last_occurred_at", DateTime(timezone=True), nullable=False),
    Column("state", JSONB, nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("generation >= 1", name="ck_journey_state_generation"),
    CheckConstraint("event_count >= 1", name="ck_journey_state_event_count"),
    CheckConstraint("state_hash ~ '^[0-9a-f]{64}$'", name="ck_journey_state_hash"),
    CheckConstraint("jsonb_typeof(state) = 'object'", name="ck_journey_state_object"),
    schema="state",
)

payment_journey_revisions = Table(
    "payment_journey_revisions",
    metadata,
    Column("revision_id", Uuid(as_uuid=True), primary_key=True),
    Column("merchant_id", String(255), nullable=False),
    Column("correlation_id", String(255), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("event_count", Integer, nullable=False),
    Column("reducer_version", String(64), nullable=False),
    Column("state_hash", String(64), nullable=False),
    Column("state", JSONB, nullable=False),
    Column(
        "reduced_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    UniqueConstraint(
        "merchant_id",
        "correlation_id",
        "generation",
        name="uq_journey_revision_generation",
    ),
    CheckConstraint("generation >= 1", name="ck_journey_revision_generation"),
    CheckConstraint("event_count >= 1", name="ck_journey_revision_event_count"),
    CheckConstraint("state_hash ~ '^[0-9a-f]{64}$'", name="ck_journey_revision_hash"),
    CheckConstraint("jsonb_typeof(state) = 'object'", name="ck_journey_revision_object"),
)

Index(
    "ix_journey_revisions_correlation",
    payment_journey_revisions.c.merchant_id,
    payment_journey_revisions.c.correlation_id,
    payment_journey_revisions.c.generation,
)

journey_reduction_attempts = Table(
    "journey_reduction_attempts",
    metadata,
    Column("attempt_id", Uuid(as_uuid=True), primary_key=True),
    Column("merchant_id", String(255), nullable=False),
    Column("correlation_id", String(255), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("worker_id", String(255), nullable=False),
    Column("reducer_version", String(64), nullable=False),
    Column("outcome", String(32), nullable=False),
    Column("error_code", String(64), nullable=True),
    Column("state_hash", String(64), nullable=True),
    Column(
        "attempted_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    UniqueConstraint(
        "merchant_id",
        "correlation_id",
        "attempt_number",
        name="uq_journey_reduction_attempt_number",
    ),
    CheckConstraint("generation >= 1", name="ck_journey_attempt_generation"),
    CheckConstraint("attempt_number >= 1", name="ck_journey_attempt_number"),
    CheckConstraint(
        "outcome IN ('completed', 'dead_letter')",
        name="ck_journey_attempt_outcome",
    ),
    CheckConstraint(
        "(outcome = 'completed' AND error_code IS NULL "
        "AND state_hash ~ '^[0-9a-f]{64}$') OR "
        "(outcome = 'dead_letter' AND error_code IS NOT NULL AND state_hash IS NULL)",
        name="ck_journey_attempt_consistent_outcome",
    ),
)

journey_reduction_replays = Table(
    "journey_reduction_replays",
    metadata,
    Column("replay_id", Uuid(as_uuid=True), primary_key=True),
    Column("merchant_id", String(255), nullable=False),
    Column("correlation_id", String(255), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("requested_by", String(255), nullable=False),
    Column("reason", Text, nullable=False),
    Column(
        "requested_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("generation >= 1", name="ck_journey_replay_generation"),
    CheckConstraint("length(trim(requested_by)) >= 1", name="ck_journey_replay_requested_by"),
    CheckConstraint("length(trim(reason)) >= 1", name="ck_journey_replay_reason"),
)

graph_projection_work = Table(
    "graph_projection_work",
    metadata,
    Column("merchant_id", String(255), primary_key=True),
    Column("correlation_id", String(255), primary_key=True),
    Column("target_version", Integer, nullable=False),
    Column("applied_version", Integer, nullable=False, server_default="0"),
    Column("state_generation", Integer, nullable=False),
    Column(
        "projection_epoch",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("projected_state_generation", Integer, nullable=True),
    Column("status", String(32), nullable=False, server_default="pending"),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("failure_count", Integer, nullable=False, server_default="0"),
    Column(
        "desired_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column(
        "available_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("lease_owner", String(255), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("last_error_code", String(64), nullable=True),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("target_version >= 1", name="ck_graph_work_target_version"),
    CheckConstraint(
        "applied_version BETWEEN 0 AND target_version",
        name="ck_graph_work_applied_version",
    ),
    CheckConstraint("state_generation >= 1", name="ck_graph_work_state_generation"),
    CheckConstraint(
        "projected_state_generation IS NULL OR projected_state_generation >= 1",
        name="ck_graph_work_projected_generation",
    ),
    CheckConstraint("attempt_count >= 0", name="ck_graph_work_attempt_count"),
    CheckConstraint("failure_count >= 0", name="ck_graph_work_failure_count"),
    CheckConstraint(
        "status IN ('pending', 'processing', 'completed', 'dead_letter')",
        name="ck_graph_work_status",
    ),
    CheckConstraint(
        "(status = 'pending' AND applied_version < target_version "
        "AND lease_owner IS NULL AND lease_expires_at IS NULL) OR "
        "(status = 'processing' AND applied_version < target_version "
        "AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
        "(status = 'completed' AND applied_version = target_version "
        "AND lease_owner IS NULL AND lease_expires_at IS NULL "
        "AND last_error_code IS NULL) OR "
        "(status = 'dead_letter' AND applied_version < target_version "
        "AND lease_owner IS NULL AND lease_expires_at IS NULL "
        "AND last_error_code IS NOT NULL)",
        name="ck_graph_work_consistent_status",
    ),
    schema="operations",
)

Index(
    "ix_graph_projection_work_claim",
    graph_projection_work.c.status,
    graph_projection_work.c.available_at,
    graph_projection_work.c.desired_at,
)

graph_projection_attempts = Table(
    "graph_projection_attempts",
    metadata,
    Column("attempt_id", Uuid(as_uuid=True), primary_key=True),
    Column("merchant_id", String(255), nullable=False),
    Column("correlation_id", String(255), nullable=False),
    Column("target_version", Integer, nullable=False),
    Column("state_generation", Integer, nullable=False),
    Column("projection_epoch", DateTime(timezone=True), nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("worker_id", String(255), nullable=False),
    Column("outcome", String(32), nullable=False),
    Column("error_code", String(64), nullable=True),
    Column("state_hash", String(64), nullable=True),
    Column(
        "attempted_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    UniqueConstraint(
        "merchant_id",
        "correlation_id",
        "attempt_number",
        name="uq_graph_projection_attempt_number",
    ),
    CheckConstraint("target_version >= 1", name="ck_graph_attempt_target_version"),
    CheckConstraint("state_generation >= 1", name="ck_graph_attempt_state_generation"),
    CheckConstraint("attempt_number >= 1", name="ck_graph_attempt_number"),
    CheckConstraint(
        "outcome IN ('completed', 'retry', 'dead_letter')",
        name="ck_graph_attempt_outcome",
    ),
    CheckConstraint(
        "(outcome = 'completed' AND error_code IS NULL "
        "AND state_hash ~ '^[0-9a-f]{64}$') OR "
        "(outcome IN ('retry', 'dead_letter') AND error_code IS NOT NULL "
        "AND state_hash IS NULL)",
        name="ck_graph_attempt_consistent_outcome",
    ),
)

graph_projection_rebuilds = Table(
    "graph_projection_rebuilds",
    metadata,
    Column("rebuild_id", Uuid(as_uuid=True), primary_key=True),
    Column("requested_by", String(255), nullable=False),
    Column("reason", Text, nullable=False),
    Column("journey_count", Integer, nullable=False),
    Column(
        "projection_epoch",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column(
        "requested_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("journey_count >= 1", name="ck_graph_rebuild_journey_count"),
    CheckConstraint("length(trim(requested_by)) >= 1", name="ck_graph_rebuild_requested_by"),
    CheckConstraint("length(trim(reason)) >= 1", name="ck_graph_rebuild_reason"),
)

graph_projection_rebuild_completions = Table(
    "graph_projection_rebuild_completions",
    metadata,
    Column("completion_id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "rebuild_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.graph_projection_rebuilds.rebuild_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("projection_epoch", DateTime(timezone=True), nullable=False),
    Column("journey_count_removed", Integer, nullable=False),
    Column("entity_count_removed", Integer, nullable=False),
    Column("event_count_removed", Integer, nullable=False),
    Column("merchant_count_removed", Integer, nullable=False),
    Column(
        "completed_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("journey_count_removed >= 0", name="ck_graph_rebuild_journeys_removed"),
    CheckConstraint("entity_count_removed >= 0", name="ck_graph_rebuild_entities_removed"),
    CheckConstraint("event_count_removed >= 0", name="ck_graph_rebuild_events_removed"),
    CheckConstraint("merchant_count_removed >= 0", name="ck_graph_rebuild_merchants_removed"),
)

invariant_evaluation_work = Table(
    "invariant_evaluation_work",
    metadata,
    Column("merchant_id", String(255), primary_key=True),
    Column("correlation_id", String(255), primary_key=True),
    Column("generation", Integer, nullable=False),
    Column("applied_generation", Integer, nullable=False, server_default="0"),
    Column("status", String(32), nullable=False, server_default="pending"),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column(
        "available_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("last_error_code", String(64), nullable=True),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("generation >= 1", name="ck_invariant_work_generation"),
    CheckConstraint(
        "applied_generation BETWEEN 0 AND generation",
        name="ck_invariant_work_applied_generation",
    ),
    CheckConstraint("attempt_count >= 0", name="ck_invariant_work_attempt_count"),
    CheckConstraint(
        "status IN ('pending', 'completed', 'dead_letter')",
        name="ck_invariant_work_status",
    ),
    CheckConstraint(
        "(status = 'pending' AND last_error_code IS NULL) OR "
        "(status = 'completed' AND applied_generation = generation "
        "AND last_error_code IS NULL) OR "
        "(status = 'dead_letter' AND applied_generation <= generation "
        "AND last_error_code IS NOT NULL)",
        name="ck_invariant_work_consistent_outcome",
    ),
    schema="operations",
)

Index(
    "ix_invariant_evaluation_work_claim",
    invariant_evaluation_work.c.status,
    invariant_evaluation_work.c.available_at,
    invariant_evaluation_work.c.updated_at,
)

invariant_evaluations = Table(
    "invariant_evaluations",
    metadata,
    Column("evaluation_id", Uuid(as_uuid=True), primary_key=True),
    Column("merchant_id", String(255), nullable=False),
    Column("correlation_id", String(255), nullable=False),
    Column("state_generation", Integer, nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("worker_id", String(255), nullable=False),
    Column("evaluator_version", String(64), nullable=False),
    Column("outcome", String(32), nullable=False),
    Column("error_code", String(64), nullable=True),
    Column("state_hash", String(64), nullable=True),
    Column("finding_count", Integer, nullable=True),
    Column("next_evaluation_at", DateTime(timezone=True), nullable=True),
    Column(
        "evaluated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    UniqueConstraint(
        "merchant_id",
        "correlation_id",
        "attempt_number",
        name="uq_invariant_evaluation_attempt",
    ),
    CheckConstraint("state_generation >= 1", name="ck_invariant_state_generation"),
    CheckConstraint("attempt_number >= 1", name="ck_invariant_attempt_number"),
    CheckConstraint("finding_count IS NULL OR finding_count >= 0", name="ck_invariant_findings"),
    CheckConstraint(
        "outcome IN ('completed', 'dead_letter')",
        name="ck_invariant_evaluation_outcome",
    ),
    CheckConstraint(
        "(outcome = 'completed' AND error_code IS NULL "
        "AND state_hash ~ '^[0-9a-f]{64}$' AND finding_count IS NOT NULL) OR "
        "(outcome = 'dead_letter' AND error_code IS NOT NULL "
        "AND state_hash IS NULL AND finding_count IS NULL)",
        name="ck_invariant_evaluation_consistent_outcome",
    ),
)

incidents = Table(
    "incidents",
    metadata,
    Column("incident_id", Uuid(as_uuid=True), primary_key=True),
    Column("incident_key", String(64), nullable=False, unique=True),
    Column("merchant_id", String(255), nullable=False),
    Column("correlation_id", String(255), nullable=False),
    Column("incident_type", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("rule_id", String(64), nullable=False),
    Column("rule_version", String(64), nullable=False),
    Column("affected_type", String(64), nullable=False),
    Column("affected_id", String(255), nullable=False),
    Column("amount_subunits", Integer, nullable=True),
    Column("currency", String(3), nullable=True),
    Column("evidence", JSONB, nullable=False),
    Column("finding_hash", String(64), nullable=False),
    Column("state_generation", Integer, nullable=False),
    Column("occurrence_count", Integer, nullable=False),
    Column("first_detected_at", DateTime(timezone=True), nullable=False),
    Column("last_detected_at", DateTime(timezone=True), nullable=False),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column(
        "last_evaluation_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.invariant_evaluations.evaluation_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("incident_key ~ '^[0-9a-f]{64}$'", name="ck_incident_key"),
    CheckConstraint("finding_hash ~ '^[0-9a-f]{64}$'", name="ck_incident_finding_hash"),
    CheckConstraint("state_generation >= 1", name="ck_incident_state_generation"),
    CheckConstraint("occurrence_count >= 1", name="ck_incident_occurrence_count"),
    CheckConstraint("jsonb_typeof(evidence) = 'array'", name="ck_incident_evidence_array"),
    CheckConstraint(
        "(amount_subunits IS NULL AND currency IS NULL) OR "
        "(amount_subunits >= 0 AND currency ~ '^[A-Z]{3}$')",
        name="ck_incident_amount",
    ),
    CheckConstraint(
        "status IN ('detected', 'investigating', 'proposed', 'awaiting_approval', "
        "'executing', 'resolved', 'failed', 'escalated')",
        name="ck_incident_status",
    ),
    CheckConstraint(
        "(status = 'resolved' AND resolved_at IS NOT NULL) OR "
        "(status <> 'resolved' AND resolved_at IS NULL)",
        name="ck_incident_resolution",
    ),
    schema="state",
)

Index("ix_incidents_status", incidents.c.status, incidents.c.last_detected_at)
Index(
    "ix_incidents_correlation",
    incidents.c.merchant_id,
    incidents.c.correlation_id,
    incidents.c.status,
)

incident_revisions = Table(
    "incident_revisions",
    metadata,
    Column("revision_id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "incident_id",
        Uuid(as_uuid=True),
        ForeignKey("state.incidents.incident_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "evaluation_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.invariant_evaluations.evaluation_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("state_generation", Integer, nullable=False),
    Column("reason", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("finding_hash", String(64), nullable=False),
    Column("snapshot", JSONB, nullable=False),
    Column(
        "recorded_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("state_generation >= 1", name="ck_incident_revision_generation"),
    CheckConstraint(
        "reason IN ('detected', 'updated', 'resolved', 'reopened')",
        name="ck_incident_revision_reason",
    ),
    CheckConstraint("finding_hash ~ '^[0-9a-f]{64}$'", name="ck_incident_revision_hash"),
    CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="ck_incident_revision_snapshot"),
)

Index(
    "ix_incident_revisions_incident",
    incident_revisions.c.incident_id,
    incident_revisions.c.recorded_at,
)

diagnosis_work = Table(
    "diagnosis_work",
    metadata,
    Column(
        "incident_id",
        Uuid(as_uuid=True),
        ForeignKey("state.incidents.incident_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column(
        "source_revision_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.incident_revisions.revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("target_version", Integer, nullable=False),
    Column("applied_version", Integer, nullable=False, server_default="0"),
    Column("status", String(32), nullable=False, server_default="pending"),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("failure_count", Integer, nullable=False, server_default="0"),
    Column("desired_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("available_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("lease_owner", String(255), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("last_error_code", String(64), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("target_version >= 1", name="ck_diagnosis_work_target_version"),
    CheckConstraint(
        "applied_version BETWEEN 0 AND target_version",
        name="ck_diagnosis_work_applied_version",
    ),
    CheckConstraint("attempt_count >= 0", name="ck_diagnosis_work_attempt_count"),
    CheckConstraint("failure_count >= 0", name="ck_diagnosis_work_failure_count"),
    CheckConstraint(
        "status IN ('pending', 'processing', 'completed', 'dead_letter')",
        name="ck_diagnosis_work_status",
    ),
    CheckConstraint(
        "(status = 'pending' AND applied_version < target_version "
        "AND lease_owner IS NULL AND lease_expires_at IS NULL) OR "
        "(status = 'processing' AND applied_version < target_version "
        "AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
        "(status = 'completed' AND applied_version = target_version "
        "AND lease_owner IS NULL AND lease_expires_at IS NULL "
        "AND last_error_code IS NULL) OR "
        "(status = 'dead_letter' AND applied_version < target_version "
        "AND lease_owner IS NULL AND lease_expires_at IS NULL "
        "AND last_error_code IS NOT NULL)",
        name="ck_diagnosis_work_consistent_status",
    ),
    schema="operations",
)

Index(
    "ix_diagnosis_work_claim",
    diagnosis_work.c.status,
    diagnosis_work.c.available_at,
    diagnosis_work.c.desired_at,
)

diagnoses = Table(
    "diagnoses",
    metadata,
    Column("diagnosis_id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "incident_id",
        Uuid(as_uuid=True),
        ForeignKey("state.incidents.incident_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "source_revision_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.incident_revisions.revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("target_version", Integer, nullable=False),
    Column("model", String(128), nullable=False),
    Column("provider_interaction_id", String(255), nullable=True),
    Column("prompt_hash", String(64), nullable=False),
    Column("subgraph_hash", String(64), nullable=False),
    Column("disposition", String(32), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("guard_reason", String(64), nullable=True),
    Column("evidence_subgraph", JSONB, nullable=False),
    Column("result", JSONB, nullable=False),
    Column("diagnosed_at", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "incident_id",
        "target_version",
        name="uq_diagnoses_incident_target",
    ),
    CheckConstraint("target_version >= 1", name="ck_diagnoses_target_version"),
    CheckConstraint("prompt_hash ~ '^[0-9a-f]{64}$'", name="ck_diagnoses_prompt_hash"),
    CheckConstraint("subgraph_hash ~ '^[0-9a-f]{64}$'", name="ck_diagnoses_subgraph_hash"),
    CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_diagnoses_confidence"),
    CheckConstraint(
        "disposition IN ('diagnosed', 'abstained')",
        name="ck_diagnoses_disposition",
    ),
    CheckConstraint(
        "(disposition = 'diagnosed' AND guard_reason IS NULL) OR disposition = 'abstained'",
        name="ck_diagnoses_guard_reason",
    ),
    CheckConstraint(
        "jsonb_typeof(evidence_subgraph) = 'object'",
        name="ck_diagnoses_evidence_object",
    ),
    CheckConstraint("jsonb_typeof(result) = 'object'", name="ck_diagnoses_result_object"),
)

Index("ix_diagnoses_incident_recorded", diagnoses.c.incident_id, diagnoses.c.recorded_at)

diagnosis_attempts = Table(
    "diagnosis_attempts",
    metadata,
    Column("attempt_id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "incident_id",
        Uuid(as_uuid=True),
        ForeignKey("state.incidents.incident_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "source_revision_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.incident_revisions.revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("target_version", Integer, nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("worker_id", String(255), nullable=False),
    Column("outcome", String(32), nullable=False),
    Column("error_code", String(64), nullable=True),
    Column(
        "diagnosis_id",
        Uuid(as_uuid=True),
        ForeignKey("ledger.diagnoses.diagnosis_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("model", String(128), nullable=True),
    Column("attempted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "incident_id",
        "attempt_number",
        name="uq_diagnosis_attempt_number",
    ),
    CheckConstraint("target_version >= 1", name="ck_diagnosis_attempt_target_version"),
    CheckConstraint("attempt_number >= 1", name="ck_diagnosis_attempt_number"),
    CheckConstraint(
        "outcome IN ('completed', 'retry', 'dead_letter')",
        name="ck_diagnosis_attempt_outcome",
    ),
    CheckConstraint(
        "(outcome = 'completed' AND error_code IS NULL "
        "AND diagnosis_id IS NOT NULL AND model IS NOT NULL) OR "
        "(outcome IN ('retry', 'dead_letter') AND error_code IS NOT NULL "
        "AND diagnosis_id IS NULL)",
        name="ck_diagnosis_attempt_consistent_outcome",
    ),
)
