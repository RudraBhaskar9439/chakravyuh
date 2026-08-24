"""Add deterministic recovery policy and crash-safe Test Mode execution ledger.

Revision ID: 20260824_0009
Revises: 20260824_0008
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0009"
down_revision: str | None = "20260824_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEDGER_TABLES = (
    "action_proposals",
    "action_policy_decisions",
    "action_approval_decisions",
    "action_execution_claims",
    "action_mutation_authorizations",
    "action_execution_results",
    "action_access_audit",
)


def upgrade() -> None:
    _create_proposals()
    _create_policy_decisions()
    _create_approval_decisions()
    _create_execution_work()
    _create_execution_ledger()
    _create_action_access_audit()
    _create_append_only_guards()


def _create_proposals() -> None:
    op.create_table(
        "action_proposals",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision_id", sa.Uuid(), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.String(length=255), nullable=False),
        sa.Column("incident_type", sa.String(length=64), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("risk", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("amount_subunits", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("rationale", sa.String(length=2000), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("proposal_hash", sa.String(length=64), nullable=False),
        sa.Column("proposed_by", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_action_proposal_confidence"),
        sa.CheckConstraint(
            "idempotency_key ~ '^[0-9a-f]{64}$'", name="ck_action_proposal_idempotency"
        ),
        sa.CheckConstraint("proposal_hash ~ '^[0-9a-f]{64}$'", name="ck_action_proposal_hash"),
        sa.CheckConstraint("expires_at > proposed_at", name="ck_action_proposal_expiry"),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_ids) = 'array'", name="ck_action_proposal_evidence_array"
        ),
        sa.CheckConstraint(
            "(amount_subunits IS NULL AND currency IS NULL) OR "
            "(amount_subunits > 0 AND currency ~ '^[A-Z]{3}$')",
            name="ck_action_proposal_amount",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["state.incidents.incident_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["ledger.incident_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["diagnosis_id"], ["ledger.diagnoses.diagnosis_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("proposal_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_action_proposal_idempotency"),
        schema="ledger",
    )
    op.create_index(
        "ix_action_proposals_incident_time",
        "action_proposals",
        ["incident_id", "proposed_at"],
        unique=False,
        schema="ledger",
    )


def _create_policy_decisions() -> None:
    op.create_table(
        "action_policy_decisions",
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('allow', 'require_approval', 'deny')",
            name="ck_action_policy_outcome",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(reasons) = 'array'", name="ck_action_policy_reasons_array"
        ),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_action_policy_input_hash"),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["ledger.action_proposals.proposal_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint("proposal_id", name="uq_action_policy_proposal"),
        schema="ledger",
    )


def _create_approval_decisions() -> None:
    op.create_table(
        "action_approval_decisions",
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.String(length=500), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')", name="ck_action_approval_decision"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["ledger.action_proposals.proposal_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("approval_id"),
        sa.UniqueConstraint("proposal_id", "principal_id", name="uq_action_approval_principal"),
        schema="ledger",
    )


def _create_execution_work() -> None:
    op.create_table(
        "action_execution_work",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'ready'"), nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("'0'"), nullable=False),
        sa.Column("latest_execution_id", sa.Uuid(), nullable=True),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "mutation_attempted", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'processing', 'retryable', 'succeeded', 'blocked', 'uncertain')",
            name="ck_action_execution_work_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_action_execution_attempt_count"),
        sa.CheckConstraint(
            "(status = 'processing' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND latest_execution_id IS NOT NULL) OR "
            "(status <> 'processing' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_action_execution_work_lease",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["ledger.action_proposals.proposal_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("proposal_id"),
        schema="operations",
    )


def _create_execution_ledger() -> None:
    op.create_table(
        "action_execution_claims",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("attempt_number >= 1", name="ck_action_execution_claim_attempt"),
        sa.CheckConstraint(
            "operation IN ('execute', 'reconcile')", name="ck_action_execution_claim_operation"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["ledger.action_proposals.proposal_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("execution_id"),
        sa.UniqueConstraint(
            "proposal_id", "attempt_number", name="uq_action_execution_claim_attempt"
        ),
        schema="ledger",
    )
    op.create_table(
        "action_mutation_authorizations",
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "authorized_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["ledger.action_execution_claims.execution_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["ledger.action_proposals.proposal_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("authorization_id"),
        sa.UniqueConstraint("execution_id", name="uq_action_mutation_execution"),
        schema="ledger",
    )
    op.create_table(
        "action_execution_results",
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("provider_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("already_applied", sa.Boolean(), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'retryable', 'blocked', 'uncertain')",
            name="ck_action_execution_result_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'succeeded' AND error_code IS NULL AND provider_state IS NOT NULL) OR "
            "(outcome <> 'succeeded' AND error_code IS NOT NULL)",
            name="ck_action_execution_result_shape",
        ),
        sa.CheckConstraint(
            "provider_state IS NULL OR jsonb_typeof(provider_state) = 'object'",
            name="ck_action_execution_provider_state_object",
        ),
        sa.CheckConstraint(
            "result_hash ~ '^[0-9a-f]{64}$'", name="ck_action_execution_result_hash"
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["ledger.action_execution_claims.execution_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["ledger.action_proposals.proposal_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("result_id"),
        sa.UniqueConstraint("execution_id", name="uq_action_execution_result_execution"),
        schema="ledger",
    )


def _create_action_access_audit() -> None:
    op.create_table(
        "action_access_audit",
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
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
            "action IN ('proposal_create', 'proposal_reuse', 'history', 'decision', "
            "'execution_claim', 'execution_idempotent')",
            name="ck_action_access_audit_action",
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'not_found', 'denied', 'conflict')",
            name="ck_action_access_audit_outcome",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object'", name="ck_action_access_audit_details_object"
        ),
        sa.PrimaryKeyConstraint("audit_id"),
        schema="ledger",
    )
    op.create_index(
        "ix_action_access_audit_principal_time",
        "action_access_audit",
        ["principal_id", "recorded_at"],
        unique=False,
        schema="ledger",
    )


def _create_append_only_guards() -> None:
    for table_name in _LEDGER_TABLES:
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
    for table_name in reversed(_LEDGER_TABLES):
        op.execute(f"DROP TRIGGER {table_name}_reject_truncate ON ledger.{table_name}")
        op.execute(f"DROP TRIGGER {table_name}_reject_mutation ON ledger.{table_name}")
    op.drop_index(
        "ix_action_access_audit_principal_time",
        table_name="action_access_audit",
        schema="ledger",
    )
    op.drop_table("action_access_audit", schema="ledger")
    op.drop_table("action_execution_results", schema="ledger")
    op.drop_table("action_mutation_authorizations", schema="ledger")
    op.drop_table("action_execution_claims", schema="ledger")
    op.drop_table("action_execution_work", schema="operations")
    op.drop_table("action_approval_decisions", schema="ledger")
    op.drop_table("action_policy_decisions", schema="ledger")
    op.drop_index(
        "ix_action_proposals_incident_time",
        table_name="action_proposals",
        schema="ledger",
    )
    op.drop_table("action_proposals", schema="ledger")
