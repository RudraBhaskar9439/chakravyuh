"""Deterministic recovery policy safety proofs."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest

from chakravyuh.domain.action_policy import (
    POLICY_VERSION,
    DeterministicRecoveryPolicy,
    RecoveryPolicyConfig,
)
from chakravyuh.domain.actions import ActionProposal, create_action_proposal
from chakravyuh.domain.enums import (
    ActionRisk,
    ActionType,
    EntityType,
    IncidentType,
    PolicyOutcome,
)
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.money import Money


class _DefaultAmount:
    pass


_DEFAULT_AMOUNT = _DefaultAmount()


def _proposal(
    *,
    merchant_id: str = "merchant-test",
    incident_type: IncidentType = IncidentType.AUTHORIZED_NOT_CAPTURED,
    action_type: ActionType = ActionType.CAPTURE_PAYMENT,
    risk: ActionRisk = ActionRisk.MONEY_MOVEMENT,
    target: EntityReference | None = None,
    amount: Money | _DefaultAmount | None = _DEFAULT_AMOUNT,
    evidence_ids: tuple[str, ...] = ("invariant:authorization-open",),
    confidence: float = 0.97,
) -> ActionProposal:
    now = datetime.now(UTC)
    resolved_amount = (
        Money(amount_subunits=10_000, currency="INR")
        if amount is _DEFAULT_AMOUNT
        else amount
        if isinstance(amount, Money)
        else None
    )
    return create_action_proposal(
        proposal_id=uuid4(),
        incident_id=uuid4(),
        source_revision_id=uuid4(),
        diagnosis_id=uuid4(),
        merchant_id=merchant_id,
        incident_type=incident_type,
        action_type=action_type,
        risk=risk,
        target=target or EntityReference(entity_type=EntityType.PAYMENT, entity_id="pay_123"),
        amount=resolved_amount,
        rationale="Capture the exact authorized payment.",
        evidence_ids=evidence_ids,
        confidence=confidence,
        idempotency_key="a" * 64,
        proposed_by="maker",
        request_id="request-1",
        proposed_at=now,
        expires_at=now + timedelta(minutes=15),
    )


def _policy(**updates: object) -> DeterministicRecoveryPolicy:
    values: dict[str, object] = {
        "actions_enabled": True,
        "test_credentials": True,
        "merchant_id": "merchant-test",
        "maximum_capture_subunits": 20_000,
        "minimum_capture_confidence": 0.9,
    }
    values.update(updates)
    return DeterministicRecoveryPolicy(RecoveryPolicyConfig.model_validate(values))


def test_exact_capture_requires_distinct_operator_approval() -> None:
    proposal = _proposal()
    decision = _policy().evaluate(proposal)

    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert decision.policy_version == POLICY_VERSION
    assert decision.reasons == ()
    assert len(decision.input_hash) == 64


def test_bounded_authoritative_fetch_is_allowed_without_money_fields() -> None:
    proposal = _proposal(
        action_type=ActionType.FETCH_AUTHORITATIVE_STATE,
        risk=ActionRisk.READ_ONLY,
        amount=None,
    )

    assert _policy().evaluate(proposal).outcome is PolicyOutcome.ALLOW


@pytest.mark.parametrize(
    ("proposal_updates", "policy_updates", "reason"),
    [
        ({}, {"actions_enabled": False}, "action_kill_switch_disabled"),
        ({}, {"test_credentials": False}, "test_credentials_not_verified"),
        ({"merchant_id": "other"}, {}, "merchant_scope_mismatch"),
        ({"evidence_ids": ()}, {}, "evidence_required"),
        ({"confidence": 0.2}, {}, "capture_confidence_below_threshold"),
        (
            {"amount": Money(amount_subunits=20_001, currency="INR")},
            {},
            "capture_amount_exceeds_limit",
        ),
        (
            {"amount": Money(amount_subunits=1_000, currency="USD")},
            {},
            "capture_currency_not_allowlisted",
        ),
        (
            {"incident_type": IncidentType.FAILED_WITHOUT_RECOVERY},
            {},
            "capture_incident_not_allowlisted",
        ),
        (
            {"action_type": ActionType.CREATE_PAYMENT_LINK, "risk": ActionRisk.REVERSIBLE},
            {},
            "action_adapter_not_implemented",
        ),
    ],
)
def test_policy_denies_every_unbounded_or_unimplemented_shape(
    proposal_updates: dict[str, object],
    policy_updates: dict[str, object],
    reason: str,
) -> None:
    proposal_factory = cast(Any, _proposal)
    decision = _policy(**policy_updates).evaluate(proposal_factory(**proposal_updates))

    assert decision.outcome is PolicyOutcome.DENY
    assert reason in decision.reasons


def test_policy_input_hash_changes_when_a_limit_changes() -> None:
    proposal = _proposal()
    first = _policy(maximum_capture_subunits=20_000).evaluate(proposal)
    second = _policy(maximum_capture_subunits=30_000).evaluate(proposal)

    assert first.input_hash != second.input_hash
