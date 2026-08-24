"""Add leased, observable, rebuildable graph projection work.

Revision ID: 20260824_0005
Revises: 20260824_0004
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0005"
down_revision: str | None = "20260824_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_TABLES = (
    "graph_projection_attempts",
    "graph_projection_rebuilds",
    "graph_projection_rebuild_completions",
)


def upgrade() -> None:
    _create_projection_work()
    _create_attempts()
    _create_rebuilds()
    _create_rebuild_completions()
    _create_enqueue_trigger()
    _backfill_work()
    _create_append_only_guards()


def _create_projection_work() -> None:
    op.create_table(
        "graph_projection_work",
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column(
            "applied_version",
            sa.Integer(),
            server_default=sa.text("'0'"),
            nullable=False,
        ),
        sa.Column("state_generation", sa.Integer(), nullable=False),
        sa.Column(
            "projection_epoch",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("projected_state_generation", sa.Integer(), nullable=True),
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
            "failure_count",
            sa.Integer(),
            server_default=sa.text("'0'"),
            nullable=False,
        ),
        sa.Column(
            "desired_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "applied_version BETWEEN 0 AND target_version",
            name="ck_graph_work_applied_version",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_graph_work_attempt_count"),
        sa.CheckConstraint("failure_count >= 0", name="ck_graph_work_failure_count"),
        sa.CheckConstraint(
            "projected_state_generation IS NULL OR projected_state_generation >= 1",
            name="ck_graph_work_projected_generation",
        ),
        sa.CheckConstraint(
            "state_generation >= 1",
            name="ck_graph_work_state_generation",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'dead_letter')",
            name="ck_graph_work_status",
        ),
        sa.CheckConstraint(
            "target_version >= 1",
            name="ck_graph_work_target_version",
        ),
        sa.PrimaryKeyConstraint("merchant_id", "correlation_id"),
        schema="operations",
    )
    op.create_index(
        "ix_graph_projection_work_claim",
        "graph_projection_work",
        ["status", "available_at", "desired_at"],
        unique=False,
        schema="operations",
    )


def _create_attempts() -> None:
    op.create_table(
        "graph_projection_attempts",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("state_generation", sa.Integer(), nullable=False),
        sa.Column("projection_epoch", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
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
            "(outcome = 'completed' AND error_code IS NULL "
            "AND state_hash ~ '^[0-9a-f]{64}$') OR "
            "(outcome IN ('retry', 'dead_letter') AND error_code IS NOT NULL "
            "AND state_hash IS NULL)",
            name="ck_graph_attempt_consistent_outcome",
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_graph_attempt_number",
        ),
        sa.CheckConstraint(
            "outcome IN ('completed', 'retry', 'dead_letter')",
            name="ck_graph_attempt_outcome",
        ),
        sa.CheckConstraint(
            "state_generation >= 1",
            name="ck_graph_attempt_state_generation",
        ),
        sa.CheckConstraint(
            "target_version >= 1",
            name="ck_graph_attempt_target_version",
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "merchant_id",
            "correlation_id",
            "attempt_number",
            name="uq_graph_projection_attempt_number",
        ),
        schema="ledger",
    )


def _create_rebuilds() -> None:
    op.create_table(
        "graph_projection_rebuilds",
        sa.Column("rebuild_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("journey_count", sa.Integer(), nullable=False),
        sa.Column(
            "projection_epoch",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "journey_count >= 1",
            name="ck_graph_rebuild_journey_count",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) >= 1",
            name="ck_graph_rebuild_reason",
        ),
        sa.CheckConstraint(
            "length(trim(requested_by)) >= 1",
            name="ck_graph_rebuild_requested_by",
        ),
        sa.PrimaryKeyConstraint("rebuild_id"),
        schema="ledger",
    )


def _create_rebuild_completions() -> None:
    op.create_table(
        "graph_projection_rebuild_completions",
        sa.Column("completion_id", sa.Uuid(), nullable=False),
        sa.Column("rebuild_id", sa.Uuid(), nullable=False),
        sa.Column("projection_epoch", sa.DateTime(timezone=True), nullable=False),
        sa.Column("journey_count_removed", sa.Integer(), nullable=False),
        sa.Column("entity_count_removed", sa.Integer(), nullable=False),
        sa.Column("event_count_removed", sa.Integer(), nullable=False),
        sa.Column("merchant_count_removed", sa.Integer(), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "journey_count_removed >= 0",
            name="ck_graph_rebuild_journeys_removed",
        ),
        sa.CheckConstraint(
            "entity_count_removed >= 0",
            name="ck_graph_rebuild_entities_removed",
        ),
        sa.CheckConstraint(
            "event_count_removed >= 0",
            name="ck_graph_rebuild_events_removed",
        ),
        sa.CheckConstraint(
            "merchant_count_removed >= 0",
            name="ck_graph_rebuild_merchants_removed",
        ),
        sa.ForeignKeyConstraint(
            ["rebuild_id"],
            ["ledger.graph_projection_rebuilds.rebuild_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("completion_id"),
        sa.UniqueConstraint("rebuild_id", name="uq_graph_rebuild_completion"),
        schema="ledger",
    )


def _create_enqueue_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION operations.enqueue_graph_projection()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO operations.graph_projection_work (
                merchant_id,
                correlation_id,
                target_version,
                state_generation
            )
            VALUES (NEW.merchant_id, NEW.correlation_id, 1, NEW.generation)
            ON CONFLICT (merchant_id, correlation_id) DO UPDATE
            SET target_version = operations.graph_projection_work.target_version + 1,
                state_generation = NEW.generation,
                status = CASE
                    WHEN operations.graph_projection_work.status = 'processing'
                    THEN 'processing'
                    ELSE 'pending'
                END,
                failure_count = 0,
                desired_at = CURRENT_TIMESTAMP,
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
        CREATE TRIGGER payment_journey_states_enqueue_graph_projection
        AFTER INSERT OR UPDATE ON state.payment_journey_states
        FOR EACH ROW EXECUTE FUNCTION operations.enqueue_graph_projection()
        """
    )


def _backfill_work() -> None:
    op.execute(
        """
        INSERT INTO operations.graph_projection_work (
            merchant_id,
            correlation_id,
            target_version,
            state_generation
        )
        SELECT merchant_id, correlation_id, 1, generation
        FROM state.payment_journey_states
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
        "DROP TRIGGER payment_journey_states_enqueue_graph_projection "
        "ON state.payment_journey_states"
    )
    op.execute("DROP FUNCTION operations.enqueue_graph_projection()")
    for table in reversed(_AUDIT_TABLES):
        op.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('ledger.{table}') IS NOT NULL THEN
                    EXECUTE 'DROP TRIGGER IF EXISTS {table}_reject_truncate '
                            'ON ledger.{table}';
                    EXECUTE 'DROP TRIGGER IF EXISTS {table}_reject_mutation '
                            'ON ledger.{table}';
                END IF;
            END;
            $$
            """
        )
    op.execute("DROP TABLE IF EXISTS ledger.graph_projection_rebuild_completions")
    op.drop_table("graph_projection_rebuilds", schema="ledger")
    op.drop_table("graph_projection_attempts", schema="ledger")
    op.drop_index(
        "ix_graph_projection_work_claim",
        table_name="graph_projection_work",
        schema="operations",
    )
    op.drop_table("graph_projection_work", schema="operations")
