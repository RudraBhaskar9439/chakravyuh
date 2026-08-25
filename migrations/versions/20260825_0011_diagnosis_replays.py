"""Add audited replay for dead-lettered grounded diagnoses.

Revision ID: 20260825_0011
Revises: 20260825_0010
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0011"
down_revision: str | None = "20260825_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "diagnosis_replays",
        sa.Column("replay_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision_id", sa.Uuid(), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("previous_error_code", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "target_version >= 1",
            name="ck_diagnosis_replay_target_version",
        ),
        sa.CheckConstraint(
            "length(trim(previous_error_code)) >= 1",
            name="ck_diagnosis_replay_previous_error",
        ),
        sa.CheckConstraint(
            "length(trim(requested_by)) >= 1",
            name="ck_diagnosis_replay_requested_by",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) >= 1",
            name="ck_diagnosis_replay_reason",
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
        sa.PrimaryKeyConstraint("replay_id"),
        schema="ledger",
    )
    op.create_index(
        "ix_diagnosis_replays_incident_time",
        "diagnosis_replays",
        ["incident_id", "requested_at"],
        unique=False,
        schema="ledger",
    )
    op.execute(
        """
        CREATE TRIGGER diagnosis_replays_reject_mutation
        BEFORE UPDATE OR DELETE ON ledger.diagnosis_replays
        FOR EACH ROW EXECUTE FUNCTION ledger.reject_normalization_audit_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER diagnosis_replays_reject_truncate
        BEFORE TRUNCATE ON ledger.diagnosis_replays
        FOR EACH STATEMENT EXECUTE FUNCTION ledger.reject_normalization_audit_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER diagnosis_replays_reject_truncate ON ledger.diagnosis_replays")
    op.execute("DROP TRIGGER diagnosis_replays_reject_mutation ON ledger.diagnosis_replays")
    op.drop_index(
        "ix_diagnosis_replays_incident_time",
        table_name="diagnosis_replays",
        schema="ledger",
    )
    op.drop_table("diagnosis_replays", schema="ledger")
