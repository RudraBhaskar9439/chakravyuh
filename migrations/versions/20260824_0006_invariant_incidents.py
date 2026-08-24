"""Add scheduled invariant evaluation and durable incident lifecycle.

Revision ID: 20260824_0006
Revises: 20260824_0005
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0006"
down_revision: str | None = "20260824_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_TABLES = ("invariant_evaluations", "incident_revisions")


def upgrade() -> None:
    _create_work()
    _create_evaluations()
    _create_incidents()
    _create_incident_revisions()
    _create_enqueue_trigger()
    _backfill_work()
    _create_append_only_guards()


def _create_work() -> None:
    op.create_table(
        "invariant_evaluation_work",
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
            name="ck_invariant_work_applied_generation",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_invariant_work_attempt_count",
        ),
        sa.CheckConstraint("generation >= 1", name="ck_invariant_work_generation"),
        sa.CheckConstraint(
            "(status = 'pending' AND last_error_code IS NULL) OR "
            "(status = 'completed' AND applied_generation = generation "
            "AND last_error_code IS NULL) OR "
            "(status = 'dead_letter' AND applied_generation <= generation "
            "AND last_error_code IS NOT NULL)",
            name="ck_invariant_work_consistent_outcome",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'dead_letter')",
            name="ck_invariant_work_status",
        ),
        sa.PrimaryKeyConstraint("merchant_id", "correlation_id"),
        schema="operations",
    )
    op.create_index(
        "ix_invariant_evaluation_work_claim",
        "invariant_evaluation_work",
        ["status", "available_at", "updated_at"],
        unique=False,
        schema="operations",
    )


def _create_evaluations() -> None:
    op.create_table(
        "invariant_evaluations",
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("state_generation", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("evaluator_version", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("state_hash", sa.String(length=64), nullable=True),
        sa.Column("finding_count", sa.Integer(), nullable=True),
        sa.Column("next_evaluation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_invariant_attempt_number",
        ),
        sa.CheckConstraint(
            "(outcome = 'completed' AND error_code IS NULL "
            "AND state_hash ~ '^[0-9a-f]{64}$' AND finding_count IS NOT NULL) OR "
            "(outcome = 'dead_letter' AND error_code IS NOT NULL "
            "AND state_hash IS NULL AND finding_count IS NULL)",
            name="ck_invariant_evaluation_consistent_outcome",
        ),
        sa.CheckConstraint(
            "outcome IN ('completed', 'dead_letter')",
            name="ck_invariant_evaluation_outcome",
        ),
        sa.CheckConstraint(
            "finding_count IS NULL OR finding_count >= 0",
            name="ck_invariant_findings",
        ),
        sa.CheckConstraint(
            "state_generation >= 1",
            name="ck_invariant_state_generation",
        ),
        sa.PrimaryKeyConstraint("evaluation_id"),
        sa.UniqueConstraint(
            "merchant_id",
            "correlation_id",
            "attempt_number",
            name="uq_invariant_evaluation_attempt",
        ),
        schema="ledger",
    )


def _create_incidents() -> None:
    op.create_table(
        "incidents",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("incident_key", sa.String(length=64), nullable=False),
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("incident_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("affected_type", sa.String(length=64), nullable=False),
        sa.Column("affected_id", sa.String(length=255), nullable=False),
        sa.Column("amount_subunits", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("finding_hash", sa.String(length=64), nullable=False),
        sa.Column("state_generation", sa.Integer(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(amount_subunits IS NULL AND currency IS NULL) OR "
            "(amount_subunits >= 0 AND currency ~ '^[A-Z]{3}$')",
            name="ck_incident_amount",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'array'",
            name="ck_incident_evidence_array",
        ),
        sa.CheckConstraint(
            "finding_hash ~ '^[0-9a-f]{64}$'",
            name="ck_incident_finding_hash",
        ),
        sa.CheckConstraint(
            "incident_key ~ '^[0-9a-f]{64}$'",
            name="ck_incident_key",
        ),
        sa.CheckConstraint(
            "occurrence_count >= 1",
            name="ck_incident_occurrence_count",
        ),
        sa.CheckConstraint(
            "(status = 'resolved' AND resolved_at IS NOT NULL) OR "
            "(status <> 'resolved' AND resolved_at IS NULL)",
            name="ck_incident_resolution",
        ),
        sa.CheckConstraint(
            "state_generation >= 1",
            name="ck_incident_state_generation",
        ),
        sa.CheckConstraint(
            "status IN ('detected', 'investigating', 'proposed', 'awaiting_approval', "
            "'executing', 'resolved', 'failed', 'escalated')",
            name="ck_incident_status",
        ),
        sa.ForeignKeyConstraint(
            ["last_evaluation_id"],
            ["ledger.invariant_evaluations.evaluation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("incident_id"),
        sa.UniqueConstraint("incident_key"),
        schema="state",
    )
    op.create_index(
        "ix_incidents_status",
        "incidents",
        ["status", "last_detected_at"],
        unique=False,
        schema="state",
    )
    op.create_index(
        "ix_incidents_correlation",
        "incidents",
        ["merchant_id", "correlation_id", "status"],
        unique=False,
        schema="state",
    )


def _create_incident_revisions() -> None:
    op.create_table(
        "incident_revisions",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("state_generation", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("finding_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "finding_hash ~ '^[0-9a-f]{64}$'",
            name="ck_incident_revision_hash",
        ),
        sa.CheckConstraint(
            "reason IN ('detected', 'updated', 'resolved', 'reopened')",
            name="ck_incident_revision_reason",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'",
            name="ck_incident_revision_snapshot",
        ),
        sa.CheckConstraint(
            "state_generation >= 1",
            name="ck_incident_revision_generation",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["ledger.invariant_evaluations.evaluation_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["state.incidents.incident_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("revision_id"),
        schema="ledger",
    )
    op.create_index(
        "ix_incident_revisions_incident",
        "incident_revisions",
        ["incident_id", "recorded_at"],
        unique=False,
        schema="ledger",
    )


def _create_enqueue_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION operations.enqueue_invariant_evaluation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO operations.invariant_evaluation_work (
                merchant_id,
                correlation_id,
                generation
            )
            VALUES (NEW.merchant_id, NEW.correlation_id, NEW.generation)
            ON CONFLICT (merchant_id, correlation_id) DO UPDATE
            SET generation = NEW.generation,
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
        CREATE TRIGGER payment_journey_states_enqueue_invariant_evaluation
        AFTER INSERT OR UPDATE ON state.payment_journey_states
        FOR EACH ROW EXECUTE FUNCTION operations.enqueue_invariant_evaluation()
        """
    )


def _backfill_work() -> None:
    op.execute(
        """
        INSERT INTO operations.invariant_evaluation_work (
            merchant_id,
            correlation_id,
            generation
        )
        SELECT merchant_id, correlation_id, generation
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
        "DROP TRIGGER payment_journey_states_enqueue_invariant_evaluation "
        "ON state.payment_journey_states"
    )
    op.execute("DROP FUNCTION operations.enqueue_invariant_evaluation()")
    for table in reversed(_AUDIT_TABLES):
        op.execute(f"DROP TRIGGER {table}_reject_truncate ON ledger.{table}")
        op.execute(f"DROP TRIGGER {table}_reject_mutation ON ledger.{table}")
    op.drop_index(
        "ix_incident_revisions_incident",
        table_name="incident_revisions",
        schema="ledger",
    )
    op.drop_table("incident_revisions", schema="ledger")
    op.drop_index("ix_incidents_correlation", table_name="incidents", schema="state")
    op.drop_index("ix_incidents_status", table_name="incidents", schema="state")
    op.drop_table("incidents", schema="state")
    op.drop_table("invariant_evaluations", schema="ledger")
    op.drop_index(
        "ix_invariant_evaluation_work_claim",
        table_name="invariant_evaluation_work",
        schema="operations",
    )
    op.drop_table("invariant_evaluation_work", schema="operations")
