"""SQLAlchemy table metadata mirrored by reviewed Alembic migrations."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
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
