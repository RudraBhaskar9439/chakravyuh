"""Persist provider-reported diagnosis token and cost usage.

Revision ID: 20260825_0012
Revises: 20260825_0011
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0012"
down_revision: str | None = "20260825_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "diagnoses",
        sa.Column("provider_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="ledger",
    )
    op.create_check_constraint(
        "ck_diagnoses_provider_usage_object",
        "diagnoses",
        "provider_usage IS NULL OR jsonb_typeof(provider_usage) = 'object'",
        schema="ledger",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_diagnoses_provider_usage_object",
        "diagnoses",
        type_="check",
        schema="ledger",
    )
    op.drop_column("diagnoses", "provider_usage", schema="ledger")
