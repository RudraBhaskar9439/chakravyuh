"""Domain contract tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from chakravyuh.domain.actions import ActionProposal, PolicyDecision, create_action_proposal
from chakravyuh.domain.enums import (
    ActionRisk,
    ActionType,
    EntityType,
    EventSource,
    IncidentType,
    PolicyOutcome,
)
from chakravyuh.domain.events import EntityReference, NormalizedEvent
from chakravyuh.domain.incidents import Incident, IncidentEvidence
from chakravyuh.domain.money import Money


class _DefaultAmount:
    pass


_DEFAULT_AMOUNT = _DefaultAmount()


def payment_ref(payment_id: str = "pay_test") -> EntityReference:
    return EntityReference(entity_type=EntityType.PAYMENT, entity_id=payment_id)


def _proposal(
    *,
    incident_id: UUID | None = None,
    action_type: ActionType = ActionType.CAPTURE_PAYMENT,
    risk: ActionRisk = ActionRisk.MONEY_MOVEMENT,
    target: EntityReference | None = None,
    amount: Money | _DefaultAmount | None = _DEFAULT_AMOUNT,
    rationale: str = "Capture the exact verified authorization.",
    evidence_ids: tuple[str, ...] = ("evidence-1",),
    confidence: float = 0.98,
) -> ActionProposal:
    now = datetime.now(UTC)
    resolved_amount = (
        Money(amount_subunits=1_000, currency="INR")
        if amount is _DEFAULT_AMOUNT
        else amount
        if isinstance(amount, Money)
        else None
    )
    return create_action_proposal(
        proposal_id=uuid4(),
        incident_id=incident_id or uuid4(),
        source_revision_id=uuid4(),
        diagnosis_id=uuid4(),
        merchant_id="merchant-1",
        incident_type=IncidentType.AUTHORIZED_NOT_CAPTURED,
        action_type=action_type,
        risk=risk,
        target=target or payment_ref(),
        amount=resolved_amount,
        rationale=rationale,
        evidence_ids=evidence_ids,
        confidence=confidence,
        idempotency_key="a" * 64,
        proposed_by="maker",
        request_id="request-1",
        proposed_at=now,
        expires_at=now + timedelta(minutes=15),
    )


def test_money_normalizes_currency_and_adds_exactly() -> None:
    left = Money(amount_subunits=125, currency="inr")
    right = Money(amount_subunits=75, currency="INR")

    assert left + right == Money(amount_subunits=200, currency="INR")


def test_money_rejects_currency_mismatch() -> None:
    with pytest.raises(ValueError, match="different currencies"):
        _ = Money(amount_subunits=100, currency="INR") + Money(
            amount_subunits=100,
            currency="USD",
        )


@pytest.mark.parametrize("currency", ["12R", "IN", "RUPE"])
def test_money_rejects_invalid_currency(currency: str) -> None:
    with pytest.raises(ValidationError):
        Money(amount_subunits=100, currency=currency)


def test_normalized_event_is_immutable_and_ordered() -> None:
    occurred_at = datetime.now(UTC)
    event = NormalizedEvent(
        merchant_id="merchant-1",
        source=EventSource.RAZORPAY_WEBHOOK,
        source_event_id="event-1",
        event_type="payment.captured",
        subject=payment_ref(),
        occurred_at=occurred_at,
        observed_at=occurred_at + timedelta(seconds=1),
        correlation_id="order-1",
        payload={"status": "captured", "amount": 1000},
    )

    assert event.schema_version == 1
    assert event.payload["status"] == "captured"
    with pytest.raises(ValidationError):
        event.__setattr__("event_type", "payment.failed")


def test_normalized_event_rejects_impossible_observation_time() -> None:
    occurred_at = datetime.now(UTC)
    with pytest.raises(ValidationError, match="observed_at cannot precede"):
        NormalizedEvent(
            merchant_id="merchant-1",
            source=EventSource.MERCHANT,
            source_event_id="event-1",
            event_type="order.created",
            subject=payment_ref(),
            occurred_at=occurred_at,
            observed_at=occurred_at - timedelta(seconds=1),
            correlation_id="order-1",
        )


def test_incident_action_and_policy_form_audit_chain() -> None:
    evidence = IncidentEvidence(
        evidence_id="evidence-1",
        description="Payment is captured in the provider state",
        entity=payment_ref(),
    )
    incident = Incident(
        merchant_id="merchant-1",
        incident_type=IncidentType.CAPTURED_BUT_ORDER_UNPAID,
        affected_entity=payment_ref(),
        amount_at_risk=Money(amount_subunits=50_000, currency="INR"),
        evidence=(evidence,),
    )
    proposal = _proposal(
        incident_id=incident.incident_id,
        action_type=ActionType.REPLAY_MERCHANT_EVENT,
        risk=ActionRisk.REVERSIBLE,
        target=payment_ref(),
        amount=incident.amount_at_risk,
        rationale="Reapply the verified captured event to the merchant order.",
        evidence_ids=(evidence.evidence_id,),
        confidence=0.98,
    )
    decision = PolicyDecision(
        proposal_id=proposal.proposal_id,
        outcome=PolicyOutcome.ALLOW,
        policy_version="phase-1",
        reasons=("Verified provider state",),
        input_hash="b" * 64,
    )

    assert proposal.incident_id == incident.incident_id
    assert decision.proposal_id == proposal.proposal_id
    assert decision.outcome is PolicyOutcome.ALLOW


def test_action_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        _proposal(confidence=1.1)
