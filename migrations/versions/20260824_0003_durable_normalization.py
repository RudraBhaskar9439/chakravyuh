"""Add durable normalization work, outputs, attempts, and replay audit.

Revision ID: 20260824_0003
Revises: 20260824_0002
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0003"
down_revision: str | None = "20260824_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_TABLES = ("normalized_events", "normalization_attempts", "normalization_replays")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS operations")
    _create_normalized_events()
    _create_work_queue()
    _create_normalization_attempts()
    _create_normalization_replays()
    _create_append_only_guards()
    op.execute(
        """
        INSERT INTO operations.webhook_normalization_work (webhook_event_id)
        SELECT event_id FROM ledger.webhook_events
        ON CONFLICT (webhook_event_id) DO NOTHING
        """
    )


def _create_normalized_events() -> None:
    op.create_table(
        "normalized_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("source_webhook_event_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("subject_type", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("normalizer_version", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "observed_at >= occurred_at",
            name="ck_normalized_observation_order",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_normalized_payload_object",
        ),
        sa.CheckConstraint("schema_version >= 1", name="ck_normalized_schema_version"),
        sa.ForeignKeyConstraint(
            ["source_webhook_event_id"],
            ["ledger.webhook_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("source_webhook_event_id"),
        sa.UniqueConstraint(
            "merchant_id",
            "source",
            "source_event_id",
            name="uq_normalized_events_provider_identity",
        ),
        schema="ledger",
    )
    op.create_index(
        "ix_normalized_events_merchant_occurred",
        "normalized_events",
        ["merchant_id", "occurred_at", "event_id"],
        unique=False,
        schema="ledger",
    )
    op.create_index(
        "ix_normalized_events_correlation",
        "normalized_events",
        ["merchant_id", "correlation_id", "occurred_at"],
        unique=False,
        schema="ledger",
    )


def _create_work_queue() -> None:
    op.create_table(
        "webhook_normalization_work",
        sa.Column("webhook_event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("'0'"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("normalized_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_normalization_work_attempt_count",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND normalized_event_id IS NOT NULL "
            "AND last_error_code IS NULL) OR "
            "(status = 'dead_letter' AND normalized_event_id IS NULL "
            "AND last_error_code IS NOT NULL) OR "
            "(status = 'pending' AND normalized_event_id IS NULL "
            "AND last_error_code IS NULL)",
            name="ck_normalization_work_consistent_outcome",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'dead_letter')",
            name="ck_normalization_work_status",
        ),
        sa.ForeignKeyConstraint(
            ["normalized_event_id"],
            ["ledger.normalized_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["webhook_event_id"],
            ["ledger.webhook_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("webhook_event_id"),
        schema="operations",
    )
    op.create_index(
        "ix_normalization_work_claim",
        "webhook_normalization_work",
        ["status", "available_at", "webhook_event_id"],
        unique=False,
        schema="operations",
    )


def _create_normalization_attempts() -> None:
    op.create_table(
        "normalization_attempts",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("webhook_event_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("normalized_event_id", sa.Uuid(), nullable=True),
        sa.Column("normalizer_version", sa.String(length=64), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(outcome = 'completed' AND normalized_event_id IS NOT NULL "
            "AND error_code IS NULL) OR "
            "(outcome = 'dead_letter' AND normalized_event_id IS NULL "
            "AND error_code IS NOT NULL)",
            name="ck_normalization_attempt_consistent_outcome",
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_normalization_attempt_number",
        ),
        sa.CheckConstraint(
            "outcome IN ('completed', 'dead_letter')",
            name="ck_normalization_attempt_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["normalized_event_id"],
            ["ledger.normalized_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["webhook_event_id"],
            ["ledger.webhook_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "webhook_event_id",
            "attempt_number",
            name="uq_normalization_attempt_number",
        ),
        schema="ledger",
    )


def _create_normalization_replays() -> None:
    op.create_table(
        "normalization_replays",
        sa.Column("replay_id", sa.Uuid(), nullable=False),
        sa.Column("webhook_event_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(reason)) >= 1",
            name="ck_replay_reason",
        ),
        sa.CheckConstraint(
            "length(trim(requested_by)) >= 1",
            name="ck_replay_requested_by",
        ),
        sa.ForeignKeyConstraint(
            ["webhook_event_id"],
            ["ledger.webhook_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("replay_id"),
        schema="ledger",
    )


def _create_append_only_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION ledger.reject_normalization_audit_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '%.% is append-only', TG_TABLE_SCHEMA, TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table in _AUDIT_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_mutation
            BEFORE UPDATE OR DELETE ON ledger.{table}
            FOR EACH ROW EXECUTE FUNCTION ledger.reject_normalization_audit_mutation()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_truncate
            BEFORE TRUNCATE ON ledger.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION ledger.reject_normalization_audit_mutation()
            """
        )


def downgrade() -> None:
    for table in reversed(_AUDIT_TABLES):
        op.execute(f"DROP TRIGGER {table}_reject_truncate ON ledger.{table}")
        op.execute(f"DROP TRIGGER {table}_reject_mutation ON ledger.{table}")
    op.execute("DROP FUNCTION ledger.reject_normalization_audit_mutation()")
    op.drop_table("normalization_replays", schema="ledger")
    op.drop_table("normalization_attempts", schema="ledger")
    op.drop_index(
        "ix_normalization_work_claim",
        table_name="webhook_normalization_work",
        schema="operations",
    )
    op.drop_table("webhook_normalization_work", schema="operations")
    op.drop_index(
        "ix_normalized_events_correlation",
        table_name="normalized_events",
        schema="ledger",
    )
    op.drop_index(
        "ix_normalized_events_merchant_occurred",
        table_name="normalized_events",
        schema="ledger",
    )
    op.drop_table("normalized_events", schema="ledger")
    op.execute("DROP SCHEMA operations")
