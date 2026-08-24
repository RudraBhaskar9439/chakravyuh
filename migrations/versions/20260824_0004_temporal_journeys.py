"""Add deterministic temporal payment-journey reduction.

Revision ID: 20260824_0004
Revises: 20260824_0003
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0004"
down_revision: str | None = "20260824_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_TABLES = (
    "payment_journey_revisions",
    "journey_reduction_attempts",
    "journey_reduction_replays",
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS state")
    _create_reduction_work()
    _create_current_state()
    _create_revisions()
    _create_attempts()
    _create_replays()
    _create_enqueue_trigger()
    _backfill_work()
    _create_append_only_guards()


def _create_reduction_work() -> None:
    op.create_table(
        "journey_reduction_work",
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column(
            "applied_generation",
            sa.Integer(),
            server_default=sa.text("'0'"),
            nullable=False,
        ),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "applied_generation BETWEEN 0 AND generation",
            name="ck_journey_work_applied_generation",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_journey_work_attempt_count",
        ),
        sa.CheckConstraint("generation >= 1", name="ck_journey_work_generation"),
        sa.CheckConstraint(
            "(status = 'pending' AND applied_generation < generation "
            "AND last_error_code IS NULL) OR "
            "(status = 'completed' AND applied_generation = generation "
            "AND last_error_code IS NULL) OR "
            "(status = 'dead_letter' AND applied_generation < generation "
            "AND last_error_code IS NOT NULL)",
            name="ck_journey_work_consistent_outcome",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'dead_letter')",
            name="ck_journey_work_status",
        ),
        sa.PrimaryKeyConstraint("merchant_id", "correlation_id"),
        schema="operations",
    )
    op.create_index(
        "ix_journey_reduction_work_claim",
        "journey_reduction_work",
        ["status", "available_at", "merchant_id", "correlation_id"],
        unique=False,
        schema="operations",
    )


def _create_current_state() -> None:
    op.create_table(
        "payment_journey_states",
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("reducer_version", sa.String(length=64), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("last_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("event_count >= 1", name="ck_journey_state_event_count"),
        sa.CheckConstraint("generation >= 1", name="ck_journey_state_generation"),
        sa.CheckConstraint(
            "state_hash ~ '^[0-9a-f]{64}$'",
            name="ck_journey_state_hash",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(state) = 'object'",
            name="ck_journey_state_object",
        ),
        sa.PrimaryKeyConstraint("merchant_id", "correlation_id"),
        schema="state",
    )


def _create_revisions() -> None:
    op.create_table(
        "payment_journey_revisions",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("reducer_version", sa.String(length=64), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "reduced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_count >= 1",
            name="ck_journey_revision_event_count",
        ),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_journey_revision_generation",
        ),
        sa.CheckConstraint(
            "state_hash ~ '^[0-9a-f]{64}$'",
            name="ck_journey_revision_hash",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(state) = 'object'",
            name="ck_journey_revision_object",
        ),
        sa.PrimaryKeyConstraint("revision_id"),
        sa.UniqueConstraint(
            "merchant_id",
            "correlation_id",
            "generation",
            name="uq_journey_revision_generation",
        ),
        schema="ledger",
    )
    op.create_index(
        "ix_journey_revisions_correlation",
        "payment_journey_revisions",
        ["merchant_id", "correlation_id", "generation"],
        unique=False,
        schema="ledger",
    )


def _create_attempts() -> None:
    op.create_table(
        "journey_reduction_attempts",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("reducer_version", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("state_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_journey_attempt_generation",
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_journey_attempt_number",
        ),
        sa.CheckConstraint(
            "(outcome = 'completed' AND error_code IS NULL "
            "AND state_hash ~ '^[0-9a-f]{64}$') OR "
            "(outcome = 'dead_letter' AND error_code IS NOT NULL AND state_hash IS NULL)",
            name="ck_journey_attempt_consistent_outcome",
        ),
        sa.CheckConstraint(
            "outcome IN ('completed', 'dead_letter')",
            name="ck_journey_attempt_outcome",
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "merchant_id",
            "correlation_id",
            "attempt_number",
            name="uq_journey_reduction_attempt_number",
        ),
        schema="ledger",
    )


def _create_replays() -> None:
    op.create_table(
        "journey_reduction_replays",
        sa.Column("replay_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_journey_replay_generation",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) >= 1",
            name="ck_journey_replay_reason",
        ),
        sa.CheckConstraint(
            "length(trim(requested_by)) >= 1",
            name="ck_journey_replay_requested_by",
        ),
        sa.PrimaryKeyConstraint("replay_id"),
        schema="ledger",
    )


def _create_enqueue_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION operations.enqueue_journey_reduction()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO operations.journey_reduction_work (
                merchant_id,
                correlation_id,
                generation
            )
            VALUES (NEW.merchant_id, NEW.correlation_id, 1)
            ON CONFLICT (merchant_id, correlation_id) DO UPDATE
            SET generation = operations.journey_reduction_work.generation + 1,
                status = 'pending',
                available_at = CURRENT_TIMESTAMP,
                last_error_code = NULL,
                updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER normalized_events_enqueue_journey_reduction
        AFTER INSERT ON ledger.normalized_events
        FOR EACH ROW EXECUTE FUNCTION operations.enqueue_journey_reduction()
        """
    )


def _backfill_work() -> None:
    op.execute(
        """
        INSERT INTO operations.journey_reduction_work (
            merchant_id,
            correlation_id,
            generation
        )
        SELECT merchant_id, correlation_id, count(*)::integer
        FROM ledger.normalized_events
        GROUP BY merchant_id, correlation_id
        ON CONFLICT (merchant_id, correlation_id) DO NOTHING
        """
    )


def _create_append_only_guards() -> None:
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
    op.execute(
        "DROP TRIGGER normalized_events_enqueue_journey_reduction ON ledger.normalized_events"
    )
    op.execute("DROP FUNCTION operations.enqueue_journey_reduction()")
    for table in reversed(_AUDIT_TABLES):
        op.execute(f"DROP TRIGGER {table}_reject_truncate ON ledger.{table}")
        op.execute(f"DROP TRIGGER {table}_reject_mutation ON ledger.{table}")
    op.drop_table("journey_reduction_replays", schema="ledger")
    op.drop_table("journey_reduction_attempts", schema="ledger")
    op.drop_index(
        "ix_journey_revisions_correlation",
        table_name="payment_journey_revisions",
        schema="ledger",
    )
    op.drop_table("payment_journey_revisions", schema="ledger")
    op.drop_table("payment_journey_states", schema="state")
    op.drop_index(
        "ix_journey_reduction_work_claim",
        table_name="journey_reduction_work",
        schema="operations",
    )
    op.drop_table("journey_reduction_work", schema="operations")
    op.execute("DROP SCHEMA state")
