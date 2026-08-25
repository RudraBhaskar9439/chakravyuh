"""Versioned deterministic policy for the deliberately narrow Phase 9 action surface."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from chakravyuh.domain.actions import ActionProposal, PolicyDecision
from chakravyuh.domain.enums import (
    ActionRisk,
    ActionType,
    EntityType,
    IncidentType,
    PolicyOutcome,
)

POLICY_VERSION = "recovery-policy-v1"


class RecoveryPolicyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actions_enabled: bool = False
    test_credentials: bool = False
    merchant_id: str | None = Field(default=None, max_length=255)
    maximum_capture_subunits: int = Field(default=1_000_000, ge=1)
    minimum_capture_confidence: float = Field(default=0.9, ge=0, le=1)
    allowed_capture_currencies: frozenset[str] = frozenset({"INR"})


class DeterministicRecoveryPolicy:
    """Deny by default; allow reads and require a checker for one exact Test Mode mutation."""

    version = POLICY_VERSION

    def __init__(
        self,
        config: RecoveryPolicyConfig,
        *,
        uuid_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._config = config
        self._uuid_factory = uuid_factory or uuid4

    def evaluate(self, proposal: ActionProposal) -> PolicyDecision:
        reasons: list[str] = []
        if not self._config.actions_enabled:
            reasons.append("action_kill_switch_disabled")
        if not self._config.test_credentials:
            reasons.append("test_credentials_not_verified")
        if self._config.merchant_id is None or proposal.merchant_id != self._config.merchant_id:
            reasons.append("merchant_scope_mismatch")
        if not proposal.evidence_ids:
            reasons.append("evidence_required")

        if proposal.action_type is ActionType.FETCH_AUTHORITATIVE_STATE:
            self._validate_fetch(proposal, reasons)
            safe_outcome = PolicyOutcome.ALLOW
        elif proposal.action_type is ActionType.CAPTURE_PAYMENT:
            self._validate_capture(proposal, reasons)
            safe_outcome = PolicyOutcome.REQUIRE_APPROVAL
        else:
            reasons.append("action_adapter_not_implemented")
            safe_outcome = PolicyOutcome.DENY

        outcome = PolicyOutcome.DENY if reasons else safe_outcome
        return PolicyDecision(
            decision_id=self._uuid_factory(),
            proposal_id=proposal.proposal_id,
            outcome=outcome,
            policy_version=self.version,
            reasons=tuple(sorted(set(reasons))),
            input_hash=self._input_hash(proposal),
            decided_at=proposal.proposed_at,
        )

    def _validate_fetch(self, proposal: ActionProposal, reasons: list[str]) -> None:
        if proposal.risk is not ActionRisk.READ_ONLY:
            reasons.append("read_action_risk_mismatch")
        if proposal.target.entity_type is not EntityType.PAYMENT:
            reasons.append("payment_target_required")
        if proposal.amount is not None:
            reasons.append("read_action_amount_forbidden")

    def _validate_capture(self, proposal: ActionProposal, reasons: list[str]) -> None:
        if proposal.incident_type is not IncidentType.AUTHORIZED_NOT_CAPTURED:
            reasons.append("capture_incident_not_allowlisted")
        if proposal.risk is not ActionRisk.MONEY_MOVEMENT:
            reasons.append("capture_risk_mismatch")
        if proposal.target.entity_type is not EntityType.PAYMENT:
            reasons.append("payment_target_required")
        if proposal.amount is None or proposal.amount.amount_subunits <= 0:
            reasons.append("positive_capture_amount_required")
        elif proposal.amount.amount_subunits > self._config.maximum_capture_subunits:
            reasons.append("capture_amount_exceeds_limit")
        if (
            proposal.amount is not None
            and proposal.amount.currency not in self._config.allowed_capture_currencies
        ):
            reasons.append("capture_currency_not_allowlisted")
        if proposal.confidence < self._config.minimum_capture_confidence:
            reasons.append("capture_confidence_below_threshold")

    def _input_hash(self, proposal: ActionProposal) -> str:
        document = {
            "actions_enabled": self._config.actions_enabled,
            "allowed_capture_currencies": sorted(self._config.allowed_capture_currencies),
            "maximum_capture_subunits": self._config.maximum_capture_subunits,
            "merchant_id": self._config.merchant_id,
            "minimum_capture_confidence": self._config.minimum_capture_confidence,
            "policy_version": self.version,
            "proposal_hash": proposal.proposal_hash,
            "test_credentials": self._config.test_credentials,
        }
        canonical = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(canonical).hexdigest()
