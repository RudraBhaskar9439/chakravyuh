"""Add append-only Test Mode Checkout order and verification proof.

Revision ID: 20260825_0010
Revises: 20260824_0009
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0010"
down_revision: str | None = "20260824_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("test_checkout_orders", "test_checkout_verifications")


def upgrade() -> None:
    op.create_table(
        "test_checkout_orders",
        sa.Column("checkout_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("order_id", sa.String(length=255), nullable=False),
        sa.Column("amount_subunits", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("receipt", sa.String(length=40), nullable=False),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint("order_id ~ '^order_[A-Za-z0-9]+$'", name="ck_test_checkout_order_id"),
        sa.CheckConstraint("amount_subunits > 0", name="ck_test_checkout_order_amount"),
        sa.CheckConstraint("currency = 'INR'", name="ck_test_checkout_order_currency"),
        sa.CheckConstraint("expires_at > created_at", name="ck_test_checkout_order_expiry"),
        sa.CheckConstraint("order_hash ~ '^[0-9a-f]{64}$'", name="ck_test_checkout_order_hash"),
        sa.PrimaryKeyConstraint("checkout_id"),
        sa.UniqueConstraint("order_id", name="uq_test_checkout_order_id"),
        sa.UniqueConstraint("receipt", name="uq_test_checkout_receipt"),
        schema="ledger",
    )
    op.create_index(
        "ix_test_checkout_orders_merchant_time",
        "test_checkout_orders",
        ["merchant_id", "created_at"],
        schema="ledger",
    )
    op.create_table(
        "test_checkout_verifications",
        sa.Column("verification_id", sa.Uuid(), nullable=False),
        sa.Column("checkout_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.String(length=255), nullable=False),
        sa.Column("order_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount_subunits", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("captured", sa.Boolean(), nullable=False),
        sa.Column("verified_by", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint("payment_id ~ '^pay_[A-Za-z0-9]+$'", name="ck_test_checkout_payment_id"),
        sa.CheckConstraint(
            "order_id ~ '^order_[A-Za-z0-9]+$'", name="ck_test_checkout_payment_order"
        ),
        sa.CheckConstraint("status = 'authorized'", name="ck_test_checkout_payment_status"),
        sa.CheckConstraint("captured = false", name="ck_test_checkout_payment_uncaptured"),
        sa.CheckConstraint("amount_subunits > 0", name="ck_test_checkout_payment_amount"),
        sa.CheckConstraint("currency = 'INR'", name="ck_test_checkout_payment_currency"),
        sa.CheckConstraint(
            "verification_hash ~ '^[0-9a-f]{64}$'",
            name="ck_test_checkout_verification_hash",
        ),
        sa.ForeignKeyConstraint(
            ["checkout_id"],
            ["ledger.test_checkout_orders.checkout_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("verification_id"),
        sa.UniqueConstraint("checkout_id", name="uq_test_checkout_verification_checkout"),
        sa.UniqueConstraint("payment_id", name="uq_test_checkout_verification_payment"),
        schema="ledger",
    )
    op.create_index(
        "ix_test_checkout_verifications_time",
        "test_checkout_verifications",
        ["verified_at"],
        schema="ledger",
    )
    for table_name in _TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_reject_mutation
            BEFORE UPDATE OR DELETE ON ledger.{table_name}
            FOR EACH ROW EXECUTE FUNCTION ledger.reject_normalization_audit_mutation()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_reject_truncate
            BEFORE TRUNCATE ON ledger.{table_name}
            FOR EACH STATEMENT EXECUTE FUNCTION ledger.reject_normalization_audit_mutation()
            """
        )


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        op.execute(f"DROP TRIGGER {table_name}_reject_truncate ON ledger.{table_name}")
        op.execute(f"DROP TRIGGER {table_name}_reject_mutation ON ledger.{table_name}")
    op.drop_index(
        "ix_test_checkout_verifications_time",
        table_name="test_checkout_verifications",
        schema="ledger",
    )
    op.drop_table("test_checkout_verifications", schema="ledger")
    op.drop_index(
        "ix_test_checkout_orders_merchant_time",
        table_name="test_checkout_orders",
        schema="ledger",
    )
    op.drop_table("test_checkout_orders", schema="ledger")
