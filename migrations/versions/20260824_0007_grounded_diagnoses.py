"""Add leased grounded diagnosis work and immutable receipts.

Revision ID: 20260824_0007
Revises: 20260824_0006
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0007"
down_revision: str | None = "20260824_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_TABLES = ("diagnoses", "diagnosis_attempts")


def upgrade() -> None:
    _create_work()
    _create_diagnoses()
    _create_attempts()
    _create_enqueue_trigger()
    _backfill_work()
    _create_append_only_guards()


def _create_work() -> None:
    op.create_table(
        "diagnosis_work",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision_id", sa.Uuid(), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("applied_version", sa.Integer(), server_default=sa.text("'0'"), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("'0'"), nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default=sa.text("'0'"), nullable=False),
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
        sa.CheckConstraint("target_version >= 1", name="ck_diagnosis_work_target_version"),
        sa.CheckConstraint(
            "applied_version BETWEEN 0 AND target_version",
            name="ck_diagnosis_work_applied_version",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_diagnosis_work_attempt_count"),
        sa.CheckConstraint("failure_count >= 0", name="ck_diagnosis_work_failure_count"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'dead_letter')",
            name="ck_diagnosis_work_status",
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
            name="ck_diagnosis_work_consistent_status",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["state.incidents.incident_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["ledger.incident_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("incident_id"),
        schema="operations",
    )
    op.create_index(
        "ix_diagnosis_work_claim",
        "diagnosis_work",
        ["status", "available_at", "desired_at"],
        unique=False,
        schema="operations",
    )


def _create_diagnoses() -> None:
    op.create_table(
        "diagnoses",
        sa.Column("diagnosis_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision_id", sa.Uuid(), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("provider_interaction_id", sa.String(length=255), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("subgraph_hash", sa.String(length=64), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("guard_reason", sa.String(length=64), nullable=True),
        sa.Column("evidence_subgraph", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diagnosed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("target_version >= 1", name="ck_diagnoses_target_version"),
        sa.CheckConstraint("prompt_hash ~ '^[0-9a-f]{64}$'", name="ck_diagnoses_prompt_hash"),
        sa.CheckConstraint("subgraph_hash ~ '^[0-9a-f]{64}$'", name="ck_diagnoses_subgraph_hash"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_diagnoses_confidence"),
        sa.CheckConstraint(
            "disposition IN ('diagnosed', 'abstained')",
            name="ck_diagnoses_disposition",
        ),
        sa.CheckConstraint(
            "(disposition = 'diagnosed' AND guard_reason IS NULL) OR disposition = 'abstained'",
            name="ck_diagnoses_guard_reason",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_subgraph) = 'object'",
            name="ck_diagnoses_evidence_object",
        ),
        sa.CheckConstraint("jsonb_typeof(result) = 'object'", name="ck_diagnoses_result_object"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["state.incidents.incident_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["ledger.incident_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("diagnosis_id"),
        sa.UniqueConstraint(
            "incident_id",
            "target_version",
            name="uq_diagnoses_incident_target",
        ),
        schema="ledger",
    )
    op.create_index(
        "ix_diagnoses_incident_recorded",
        "diagnoses",
        ["incident_id", "recorded_at"],
        unique=False,
        schema="ledger",
    )


def _create_attempts() -> None:
    op.create_table(
        "diagnosis_attempts",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision_id", sa.Uuid(), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("target_version >= 1", name="ck_diagnosis_attempt_target_version"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_diagnosis_attempt_number"),
        sa.CheckConstraint(
            "outcome IN ('completed', 'retry', 'dead_letter')",
            name="ck_diagnosis_attempt_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'completed' AND error_code IS NULL "
            "AND diagnosis_id IS NOT NULL AND model IS NOT NULL) OR "
            "(outcome IN ('retry', 'dead_letter') AND error_code IS NOT NULL "
            "AND diagnosis_id IS NULL)",
            name="ck_diagnosis_attempt_consistent_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["state.incidents.incident_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["ledger.incident_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["diagnosis_id"],
            ["ledger.diagnoses.diagnosis_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "incident_id",
            "attempt_number",
            name="uq_diagnosis_attempt_number",
        ),
        schema="ledger",
    )


def _create_enqueue_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION operations.enqueue_incident_diagnosis()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.reason = 'resolved' THEN
                UPDATE operations.diagnosis_work
                SET source_revision_id = NEW.revision_id,
                    target_version = target_version + 1,
                    applied_version = target_version + 1,
                    status = 'completed',
                    failure_count = 0,
                    desired_at = CURRENT_TIMESTAMP,
                    available_at = CURRENT_TIMESTAMP,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    last_error_code = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE incident_id = NEW.incident_id;
                RETURN NEW;
            END IF;
            INSERT INTO operations.diagnosis_work (
                incident_id,
                source_revision_id,
                target_version
            )
            VALUES (NEW.incident_id, NEW.revision_id, 1)
            ON CONFLICT (incident_id) DO UPDATE
            SET source_revision_id = NEW.revision_id,
                target_version = operations.diagnosis_work.target_version + 1,
                status = CASE
                    WHEN operations.diagnosis_work.status = 'processing' THEN 'processing'
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
        CREATE TRIGGER incident_revisions_enqueue_diagnosis
        AFTER INSERT ON ledger.incident_revisions
        FOR EACH ROW EXECUTE FUNCTION operations.enqueue_incident_diagnosis()
        """
    )


def _backfill_work() -> None:
    op.execute(
        """
        INSERT INTO operations.diagnosis_work (
            incident_id,
            source_revision_id,
            target_version
        )
        SELECT DISTINCT ON (revision.incident_id)
            revision.incident_id,
            revision.revision_id,
            1
        FROM ledger.incident_revisions AS revision
        JOIN state.incidents AS incident ON incident.incident_id = revision.incident_id
        WHERE revision.reason <> 'resolved' AND incident.status <> 'resolved'
        ORDER BY revision.incident_id, revision.recorded_at DESC, revision.revision_id DESC
        ON CONFLICT (incident_id) DO NOTHING
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
    op.execute("DROP TRIGGER incident_revisions_enqueue_diagnosis ON ledger.incident_revisions")
    op.execute("DROP FUNCTION operations.enqueue_incident_diagnosis()")
    for table in reversed(_AUDIT_TABLES):
        op.execute(f"DROP TRIGGER {table}_reject_truncate ON ledger.{table}")
        op.execute(f"DROP TRIGGER {table}_reject_mutation ON ledger.{table}")
    op.drop_table("diagnosis_attempts", schema="ledger")
    op.drop_index(
        "ix_diagnoses_incident_recorded",
        table_name="diagnoses",
        schema="ledger",
    )
    op.drop_table("diagnoses", schema="ledger")
    op.drop_index(
        "ix_diagnosis_work_claim",
        table_name="diagnosis_work",
        schema="operations",
    )
    op.drop_table("diagnosis_work", schema="operations")
