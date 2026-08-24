"""Add immutable operator read-access audit.

Revision ID: 20260824_0008
Revises: 20260824_0007
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0008"
down_revision: str | None = "20260824_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_read_audit",
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('overview', 'incident_list', 'incident_detail')",
            name="ck_operator_read_audit_action",
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'not_found')",
            name="ck_operator_read_audit_outcome",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object'",
            name="ck_operator_read_audit_details_object",
        ),
        sa.CheckConstraint(
            "length(trim(principal_id)) BETWEEN 1 AND 64",
            name="ck_operator_read_audit_principal",
        ),
        sa.CheckConstraint(
            "length(trim(request_id)) BETWEEN 1 AND 255",
            name="ck_operator_read_audit_request",
        ),
        sa.PrimaryKeyConstraint("audit_id"),
        schema="ledger",
    )
    op.create_index(
        "ix_operator_read_audit_principal_time",
        "operator_read_audit",
        ["principal_id", "recorded_at"],
        unique=False,
        schema="ledger",
    )
    op.execute(
        """
        CREATE TRIGGER operator_read_audit_reject_mutation
        BEFORE UPDATE OR DELETE ON ledger.operator_read_audit
        FOR EACH ROW EXECUTE FUNCTION ledger.reject_normalization_audit_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER operator_read_audit_reject_truncate
        BEFORE TRUNCATE ON ledger.operator_read_audit
        FOR EACH STATEMENT EXECUTE FUNCTION ledger.reject_normalization_audit_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER operator_read_audit_reject_truncate ON ledger.operator_read_audit")
    op.execute("DROP TRIGGER operator_read_audit_reject_mutation ON ledger.operator_read_audit")
    op.drop_index(
        "ix_operator_read_audit_principal_time",
        table_name="operator_read_audit",
        schema="ledger",
    )
    op.drop_table("operator_read_audit", schema="ledger")
