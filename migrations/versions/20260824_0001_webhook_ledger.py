"""Create the immutable verified-webhook ledger.

Revision ID: 20260824_0001
Revises: None
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ledger")
    op.create_table(
        "webhook_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_body", sa.LargeBinary(), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "body_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_webhook_body_sha256",
        ),
        sa.CheckConstraint(
            "octet_length(raw_body) BETWEEN 1 AND 262144",
            name="ck_webhook_body_size",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_webhook_payload_object",
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint(
            "merchant_id",
            "source",
            "source_event_id",
            name="uq_webhook_events_provider_identity",
        ),
        schema="ledger",
    )
    op.create_index(
        "ix_webhook_events_merchant_observed",
        "webhook_events",
        ["merchant_id", "observed_at", "event_id"],
        unique=False,
        schema="ledger",
    )
    op.execute(
        """
        CREATE FUNCTION ledger.reject_webhook_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'ledger.webhook_events is append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER webhook_events_reject_mutation
        BEFORE UPDATE OR DELETE ON ledger.webhook_events
        FOR EACH ROW EXECUTE FUNCTION ledger.reject_webhook_event_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER webhook_events_reject_truncate
        BEFORE TRUNCATE ON ledger.webhook_events
        FOR EACH STATEMENT EXECUTE FUNCTION ledger.reject_webhook_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER webhook_events_reject_truncate ON ledger.webhook_events")
    op.execute("DROP TRIGGER webhook_events_reject_mutation ON ledger.webhook_events")
    op.drop_index(
        "ix_webhook_events_merchant_observed",
        table_name="webhook_events",
        schema="ledger",
    )
    op.drop_table("webhook_events", schema="ledger")
    op.execute("DROP FUNCTION ledger.reject_webhook_event_mutation()")
    op.execute("DROP SCHEMA ledger")
