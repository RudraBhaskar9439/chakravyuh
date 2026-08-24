"""SQLAlchemy table metadata mirrored by reviewed Alembic migrations."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    LargeBinary,
    MetaData,
    String,
    Table,
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
