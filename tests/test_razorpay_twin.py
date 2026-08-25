"""Deterministic provider-twin state, fault, webhook, and isolation proofs."""

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from chakravyuh.application.ports import RazorpayPaymentGateway
from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.enums import PaymentStatus
from chakravyuh.domain.errors import ActionControlErrorCode, RazorpayActionError
from chakravyuh.domain.money import Money
from chakravyuh.infrastructure.razorpay.normalizer import RazorpayWebhookNormalizer
from chakravyuh.simulation.razorpay_twin import (
    ArenaProviderFault,
    ArenaProviderOperationOutcome,
    ArenaProviderPlan,
    ArenaProviderSnapshot,
    DeterministicRazorpayTwin,
    build_provider_plan_hash,
    create_provider_plan,
)


def _state(
    status: PaymentStatus = PaymentStatus.AUTHORIZED,
    *,
    captured: bool = False,
) -> ProviderPaymentState:
    return ProviderPaymentState(
        payment_id="pay_arena123",
        status=status,
        amount=Money(amount_subunits=10_000, currency="INR"),
        captured=captured,
        order_id="order_arena123",
    )


def _plan(
    fault: ArenaProviderFault = ArenaProviderFault.NONE,
    *,
    fault_on_capture_attempt: int = 1,
    state_after_change: ProviderPaymentState | None = None,
    duplicate_confirmation_deliveries: int = 0,
    started_at: datetime | None = None,
) -> ArenaProviderPlan:
    return create_provider_plan(
        case_id="case-123",
        merchant_id="merchant-arena",
        account_id="acc_arena123",
        initial_state=_state(),
        capture_fault=fault,
        fault_on_capture_attempt=fault_on_capture_attempt,
        state_after_change=state_after_change,
        duplicate_confirmation_deliveries=duplicate_confirmation_deliveries,
        started_at=started_at,
    )


async def test_successful_capture_is_exactly_once_and_emits_normalizable_confirmation() -> None:
    twin = DeterministicRazorpayTwin(_plan(duplicate_confirmation_deliveries=1))
    gateway = twin.strategy_gateway()

    before = await gateway.fetch_payment("pay_arena123")
    captured = await gateway.capture_payment("pay_arena123", before.amount)
    already_applied = await gateway.capture_payment("pay_arena123", before.amount)
    webhooks = await twin.drain_webhooks()
    snapshot = await twin.snapshot()

    assert captured.status is PaymentStatus.CAPTURED and captured.captured
    assert already_applied == captured
    assert snapshot.applied_mutation_count == 1
    assert [item.outcome for item in snapshot.operations] == [
        ArenaProviderOperationOutcome.RETURNED,
        ArenaProviderOperationOutcome.APPLIED,
        ArenaProviderOperationOutcome.ALREADY_APPLIED,
    ]
    assert len(webhooks) == 2 and webhooks[0] == webhooks[1]
    normalized = RazorpayWebhookNormalizer().normalize(webhooks[0])
    assert normalized.event_type == "payment.captured"
    assert normalized.payload["captured"] is True
    assert normalized.correlation_id == "order_arena123"


async def test_timeout_before_mutation_leaves_state_and_webhooks_unchanged() -> None:
    twin = DeterministicRazorpayTwin(_plan(ArenaProviderFault.TIMEOUT_BEFORE_MUTATION))
    gateway = twin.strategy_gateway()

    with pytest.raises(RazorpayActionError) as captured:
        await gateway.capture_payment("pay_arena123", _state().amount)

    snapshot = await twin.snapshot()
    assert captured.value.retryable
    assert captured.value.code is ActionControlErrorCode.PROVIDER_UNAVAILABLE
    assert snapshot.state.status is PaymentStatus.AUTHORIZED
    assert snapshot.applied_mutation_count == 0
    assert snapshot.operations[-1].outcome is (
        ArenaProviderOperationOutcome.TIMEOUT_BEFORE_MUTATION
    )
    assert await twin.drain_webhooks() == ()


async def test_timeout_after_mutation_is_reconcilable_without_second_mutation() -> None:
    twin = DeterministicRazorpayTwin(_plan(ArenaProviderFault.TIMEOUT_AFTER_MUTATION))
    gateway = twin.strategy_gateway()

    with pytest.raises(RazorpayActionError) as captured:
        await gateway.capture_payment("pay_arena123", _state().amount)
    reconciled = await gateway.fetch_payment("pay_arena123")
    repeated = await gateway.capture_payment("pay_arena123", _state().amount)
    snapshot = await twin.snapshot()

    assert captured.value.retryable
    assert reconciled.status is PaymentStatus.CAPTURED
    assert repeated == reconciled
    assert snapshot.applied_mutation_count == 1
    assert snapshot.operations[0].outcome is (ArenaProviderOperationOutcome.TIMEOUT_AFTER_MUTATION)
    assert snapshot.operations[-1].outcome is ArenaProviderOperationOutcome.ALREADY_APPLIED
    assert len(await twin.drain_webhooks()) == 1


async def test_rejected_capture_is_permanent_and_has_no_mutation() -> None:
    twin = DeterministicRazorpayTwin(_plan(ArenaProviderFault.REJECT_CAPTURE))

    with pytest.raises(RazorpayActionError) as captured:
        await twin.strategy_gateway().capture_payment("pay_arena123", _state().amount)

    snapshot = await twin.snapshot()
    assert not captured.value.retryable
    assert captured.value.code is ActionControlErrorCode.PROVIDER_REJECTED
    assert snapshot.applied_mutation_count == 0
    assert snapshot.operations[-1].outcome is ArenaProviderOperationOutcome.REJECTED


async def test_state_change_during_capture_is_predetermined_and_not_credited_as_recovery() -> None:
    failed = _state(PaymentStatus.FAILED)
    twin = DeterministicRazorpayTwin(
        _plan(
            ArenaProviderFault.STATE_CHANGED_DURING_CAPTURE,
            state_after_change=failed,
        )
    )

    with pytest.raises(RazorpayActionError) as captured:
        await twin.strategy_gateway().capture_payment("pay_arena123", _state().amount)

    snapshot = await twin.snapshot()
    assert captured.value.code is ActionControlErrorCode.AUTHORITATIVE_STATE_CHANGED
    assert snapshot.state.status is PaymentStatus.FAILED
    assert snapshot.applied_mutation_count == 0
    assert snapshot.operations[-1].outcome is ArenaProviderOperationOutcome.STATE_CHANGED
    assert await twin.drain_webhooks() == ()


async def test_wrong_payment_or_amount_is_rejected_and_audited() -> None:
    twin = DeterministicRazorpayTwin(_plan())
    gateway = twin.strategy_gateway()

    with pytest.raises(RazorpayActionError) as wrong_payment:
        await gateway.fetch_payment("pay_other")
    with pytest.raises(RazorpayActionError) as wrong_amount:
        await gateway.capture_payment(
            "pay_arena123",
            Money(amount_subunits=9_999, currency="INR"),
        )

    snapshot = await twin.snapshot()
    assert wrong_payment.value.code is ActionControlErrorCode.PROVIDER_INVALID_RESPONSE
    assert wrong_amount.value.code is ActionControlErrorCode.AUTHORITATIVE_STATE_CHANGED
    assert all(
        item.outcome is ArenaProviderOperationOutcome.INVALID_REQUEST
        for item in snapshot.operations
    )


async def test_non_authorized_payment_is_never_captured() -> None:
    plan = create_provider_plan(
        case_id="case-failed",
        merchant_id="merchant-arena",
        account_id="acc_arena123",
        initial_state=_state(PaymentStatus.FAILED),
    )
    twin = DeterministicRazorpayTwin(plan)

    with pytest.raises(RazorpayActionError) as captured:
        await twin.strategy_gateway().capture_payment("pay_arena123", _state().amount)

    assert captured.value.code is ActionControlErrorCode.PROVIDER_REJECTED
    assert (await twin.snapshot()).applied_mutation_count == 0


async def test_closed_twin_fails_fetch_and_capture_without_mutation() -> None:
    twin = DeterministicRazorpayTwin(_plan())
    gateway = twin.strategy_gateway()
    await gateway.close()

    with pytest.raises(RazorpayActionError):
        await gateway.fetch_payment("pay_arena123")
    with pytest.raises(RazorpayActionError):
        await gateway.capture_payment("pay_arena123", _state().amount)

    snapshot = await twin.snapshot()
    assert snapshot.applied_mutation_count == 0
    assert [item.outcome for item in snapshot.operations] == [
        ArenaProviderOperationOutcome.CLOSED,
        ArenaProviderOperationOutcome.CLOSED,
    ]


async def test_independent_twins_are_reproducible_and_do_not_share_state() -> None:
    plan = _plan(ArenaProviderFault.TIMEOUT_AFTER_MUTATION)
    first = DeterministicRazorpayTwin(plan)
    second = DeterministicRazorpayTwin(plan)

    for twin in (first, second):
        with pytest.raises(RazorpayActionError):
            await twin.strategy_gateway().capture_payment("pay_arena123", _state().amount)

    first_snapshot = await first.snapshot()
    second_snapshot = await second.snapshot()
    assert first_snapshot == second_snapshot
    await first.drain_webhooks()
    assert (await first.snapshot()).pending_webhook_count == 0
    assert (await second.snapshot()).pending_webhook_count == 1


async def test_concurrent_capture_requests_apply_one_mutation() -> None:
    twin = DeterministicRazorpayTwin(_plan())
    gateway = twin.strategy_gateway()

    states = await asyncio.gather(
        *(gateway.capture_payment("pay_arena123", _state().amount) for _ in range(20))
    )
    snapshot = await twin.snapshot()

    assert all(state.status is PaymentStatus.CAPTURED for state in states)
    assert snapshot.applied_mutation_count == 1
    assert (
        sum(item.outcome is ArenaProviderOperationOutcome.APPLIED for item in snapshot.operations)
        == 1
    )
    assert len(await twin.drain_webhooks()) == 1


def test_strategy_gateway_exposes_only_provider_protocol() -> None:
    gateway = DeterministicRazorpayTwin(_plan()).strategy_gateway()
    typed: RazorpayPaymentGateway = gateway

    assert callable(typed.fetch_payment)
    assert callable(typed.capture_payment)
    assert callable(typed.close)
    assert not hasattr(gateway, "snapshot")
    assert not hasattr(gateway, "drain_webhooks")
    assert not hasattr(gateway, "plan")
    assert not hasattr(gateway, "oracle")


def test_plan_hash_is_stable_and_tampering_is_rejected() -> None:
    plan = _plan()
    same = _plan()

    assert plan == same
    assert plan.plan_sha256 == build_provider_plan_hash(plan)
    with pytest.raises(ValidationError, match="plan hash"):
        ArenaProviderPlan.model_validate({**plan.model_dump(), "plan_sha256": "f" * 64})


async def test_snapshot_hash_or_mutation_count_tampering_is_rejected() -> None:
    twin = DeterministicRazorpayTwin(_plan())
    await twin.strategy_gateway().capture_payment("pay_arena123", _state().amount)
    snapshot = await twin.snapshot()

    with pytest.raises(ValidationError, match="snapshot hash"):
        ArenaProviderSnapshot.model_validate({**snapshot.model_dump(), "snapshot_sha256": "f" * 64})
    with pytest.raises(ValidationError, match="mutation count"):
        ArenaProviderSnapshot.model_validate({**snapshot.model_dump(), "applied_mutation_count": 0})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"state_after_change": _state(PaymentStatus.FAILED)}, "accepted only"),
        (
            {
                "capture_fault": ArenaProviderFault.STATE_CHANGED_DURING_CAPTURE,
                "state_after_change": None,
            },
            "requires",
        ),
        (
            {
                "capture_fault": ArenaProviderFault.STATE_CHANGED_DURING_CAPTURE,
                "state_after_change": _state(PaymentStatus.CAPTURED, captured=True),
            },
            "action-dependent",
        ),
        (
            {
                "capture_fault": ArenaProviderFault.STATE_CHANGED_DURING_CAPTURE,
                "state_after_change": _state(PaymentStatus.FAILED).model_copy(
                    update={"payment_id": "pay_other"}
                ),
            },
            "retain payment identity",
        ),
        (
            {"started_at": datetime(2026, 8, 25, tzinfo=UTC).replace(tzinfo=None)},
            "timezone",
        ),
        (
            {
                "initial_state": _state().model_copy(
                    update={"amount": Money(amount_subunits=10_000, currency="USD")}
                )
            },
            "INR",
        ),
    ],
)
def test_plan_rejects_ambiguous_or_unfair_faults(changes: dict[str, object], message: str) -> None:
    plan = _plan()
    document = {**plan.model_dump(), **changes}
    draft = plan.model_copy(update=changes)
    document["plan_sha256"] = build_provider_plan_hash(draft)

    with pytest.raises(ValidationError, match=message):
        ArenaProviderPlan.model_validate(document)


def test_plan_accepts_explicit_utc_timestamp() -> None:
    plan = create_provider_plan(
        case_id="case-time",
        merchant_id="merchant-arena",
        account_id="acc_arena123",
        initial_state=_state(),
        started_at=datetime(2026, 8, 25, 12, tzinfo=UTC),
    )

    assert plan.started_at == datetime(2026, 8, 25, 12, tzinfo=UTC)
