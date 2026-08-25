"""Deterministic Razorpay-shaped provider twin for counterfactual recovery evaluation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from chakravyuh.application.ports import RazorpayPaymentGateway
from chakravyuh.domain.actions import ProviderPaymentState
from chakravyuh.domain.enums import EventSource, PaymentStatus
from chakravyuh.domain.errors import ActionControlErrorCode, RazorpayActionError
from chakravyuh.domain.money import Money
from chakravyuh.domain.webhooks import RawWebhookEvent


class ArenaProviderFault(StrEnum):
    NONE = "none"
    REJECT_CAPTURE = "reject_capture"
    TIMEOUT_BEFORE_MUTATION = "timeout_before_mutation"
    TIMEOUT_AFTER_MUTATION = "timeout_after_mutation"
    STATE_CHANGED_DURING_CAPTURE = "state_changed_during_capture"


class ArenaProviderOperation(StrEnum):
    FETCH = "fetch"
    CAPTURE = "capture"


class ArenaProviderOperationOutcome(StrEnum):
    RETURNED = "returned"
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    REJECTED = "rejected"
    TIMEOUT_BEFORE_MUTATION = "timeout_before_mutation"
    TIMEOUT_AFTER_MUTATION = "timeout_after_mutation"
    STATE_CHANGED = "state_changed"
    INVALID_REQUEST = "invalid_request"
    CLOSED = "closed"


class ArenaProviderPlan(BaseModel):
    """Evaluator-only predetermined provider behavior for one independent strategy clone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_version: str = Field(pattern=r"^razorpay-twin-plan-v[0-9]+$")
    case_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    merchant_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    account_id: str = Field(pattern=r"^acc_[A-Za-z0-9]+$", max_length=255)
    initial_state: ProviderPaymentState
    capture_fault: ArenaProviderFault
    fault_on_capture_attempt: int = Field(default=1, ge=1, le=100)
    state_after_change: ProviderPaymentState | None = None
    duplicate_confirmation_deliveries: int = Field(default=0, ge=0, le=10)
    started_at: AwareDatetime
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if self.started_at.utcoffset() is None:
            msg = "provider twin start time must be timezone-aware"
            raise ValueError(msg)
        if self.initial_state.amount.currency != "INR":
            msg = "provider twin v1 accepts INR payment state only"
            raise ValueError(msg)
        if self.capture_fault is ArenaProviderFault.STATE_CHANGED_DURING_CAPTURE:
            if self.state_after_change is None:
                msg = "state-change fault requires a predetermined replacement state"
                raise ValueError(msg)
            if (
                self.state_after_change.payment_id != self.initial_state.payment_id
                or self.state_after_change.amount != self.initial_state.amount
                or self.state_after_change.order_id != self.initial_state.order_id
            ):
                msg = "state-change replacement must retain payment identity, amount, and order"
                raise ValueError(msg)
            if self.state_after_change.status is PaymentStatus.CAPTURED:
                msg = "state-change fault cannot create action-dependent external recovery"
                raise ValueError(msg)
        elif self.state_after_change is not None:
            msg = "replacement state is accepted only for the state-change fault"
            raise ValueError(msg)
        if build_provider_plan_hash(self) != self.plan_sha256:
            msg = "provider twin plan hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ArenaProviderOperationReceipt(BaseModel):
    """Secret-free immutable observation of one provider boundary call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: UUID
    sequence: int = Field(ge=1)
    operation: ArenaProviderOperation
    payment_id: str
    amount: Money | None = None
    capture_attempt: int | None = Field(default=None, ge=1)
    outcome: ArenaProviderOperationOutcome
    mutation_applied: bool
    state_before_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_after_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_receipt_hash(self) -> Self:
        if (self.operation is ArenaProviderOperation.CAPTURE) != (self.capture_attempt is not None):
            msg = "capture attempts belong only to capture operations"
            raise ValueError(msg)
        mutation_outcomes = {
            ArenaProviderOperationOutcome.APPLIED,
            ArenaProviderOperationOutcome.TIMEOUT_AFTER_MUTATION,
        }
        if self.mutation_applied != (self.outcome in mutation_outcomes):
            msg = "mutation flag must agree with the provider operation outcome"
            raise ValueError(msg)
        if _receipt_hash(self) != self.receipt_sha256:
            msg = "provider twin receipt hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ArenaProviderSnapshot(BaseModel):
    """Evaluator-owned state and evidence; never supplied to a strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: ProviderPaymentState
    operations: tuple[ArenaProviderOperationReceipt, ...]
    pending_webhook_count: int = Field(ge=0)
    applied_mutation_count: int = Field(ge=0)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if tuple(item.sequence for item in self.operations) != tuple(
            range(1, len(self.operations) + 1)
        ):
            msg = "provider operation sequence must be contiguous"
            raise ValueError(msg)
        if self.applied_mutation_count != sum(item.mutation_applied for item in self.operations):
            msg = "provider applied-mutation count must match immutable receipts"
            raise ValueError(msg)
        if _snapshot_hash(self) != self.snapshot_sha256:
            msg = "provider twin snapshot hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ArenaTwinGateway:
    """Strategy-visible narrow gateway with no oracle or evaluator methods."""

    __slots__ = ("__twin",)

    def __init__(self, twin: DeterministicRazorpayTwin) -> None:
        self.__twin = twin

    async def fetch_payment(self, payment_id: str) -> ProviderPaymentState:
        return await self.__twin.fetch_payment(payment_id)

    async def capture_payment(self, payment_id: str, amount: Money) -> ProviderPaymentState:
        return await self.__twin.capture_payment(payment_id, amount)

    async def close(self) -> None:
        await self.__twin.close()


class DeterministicRazorpayTwin:
    """Independent, concurrency-safe provider state machine with predetermined faults."""

    def __init__(self, plan: ArenaProviderPlan) -> None:
        self._plan = plan
        self._state = plan.initial_state
        self._operations: list[ArenaProviderOperationReceipt] = []
        self._pending_webhooks: list[RawWebhookEvent] = []
        self._capture_attempts = 0
        self._applied_mutations = 0
        self._closed = False
        self._lock = asyncio.Lock()

    def strategy_gateway(self) -> RazorpayPaymentGateway:
        return ArenaTwinGateway(self)

    async def fetch_payment(self, payment_id: str) -> ProviderPaymentState:
        async with self._lock:
            before = self._state
            if self._closed:
                self._record(
                    ArenaProviderOperation.FETCH,
                    payment_id,
                    None,
                    ArenaProviderOperationOutcome.CLOSED,
                    before,
                    before,
                )
                raise _provider_error(ActionControlErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
            if payment_id != self._state.payment_id:
                self._record(
                    ArenaProviderOperation.FETCH,
                    payment_id,
                    None,
                    ArenaProviderOperationOutcome.INVALID_REQUEST,
                    before,
                    before,
                )
                raise _provider_error(
                    ActionControlErrorCode.PROVIDER_INVALID_RESPONSE,
                    retryable=False,
                )
            self._record(
                ArenaProviderOperation.FETCH,
                payment_id,
                None,
                ArenaProviderOperationOutcome.RETURNED,
                before,
                before,
            )
            return self._state

    async def capture_payment(self, payment_id: str, amount: Money) -> ProviderPaymentState:
        async with self._lock:
            before = self._state
            self._capture_attempts += 1
            attempt = self._capture_attempts
            if self._closed:
                self._record(
                    ArenaProviderOperation.CAPTURE,
                    payment_id,
                    amount,
                    ArenaProviderOperationOutcome.CLOSED,
                    before,
                    before,
                    capture_attempt=attempt,
                )
                raise _provider_error(ActionControlErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
            if payment_id != before.payment_id or amount != before.amount:
                self._record(
                    ArenaProviderOperation.CAPTURE,
                    payment_id,
                    amount,
                    ArenaProviderOperationOutcome.INVALID_REQUEST,
                    before,
                    before,
                    capture_attempt=attempt,
                )
                raise _provider_error(
                    ActionControlErrorCode.AUTHORITATIVE_STATE_CHANGED,
                    retryable=False,
                )
            if before.status is PaymentStatus.CAPTURED and before.captured:
                self._record(
                    ArenaProviderOperation.CAPTURE,
                    payment_id,
                    amount,
                    ArenaProviderOperationOutcome.ALREADY_APPLIED,
                    before,
                    before,
                    capture_attempt=attempt,
                )
                return before
            if before.status is not PaymentStatus.AUTHORIZED or before.captured:
                self._record(
                    ArenaProviderOperation.CAPTURE,
                    payment_id,
                    amount,
                    ArenaProviderOperationOutcome.REJECTED,
                    before,
                    before,
                    capture_attempt=attempt,
                )
                raise _provider_error(ActionControlErrorCode.PROVIDER_REJECTED, retryable=False)

            fault = (
                self._plan.capture_fault
                if attempt == self._plan.fault_on_capture_attempt
                else ArenaProviderFault.NONE
            )
            if fault is ArenaProviderFault.REJECT_CAPTURE:
                self._record(
                    ArenaProviderOperation.CAPTURE,
                    payment_id,
                    amount,
                    ArenaProviderOperationOutcome.REJECTED,
                    before,
                    before,
                    capture_attempt=attempt,
                )
                raise _provider_error(ActionControlErrorCode.PROVIDER_REJECTED, retryable=False)
            if fault is ArenaProviderFault.TIMEOUT_BEFORE_MUTATION:
                self._record(
                    ArenaProviderOperation.CAPTURE,
                    payment_id,
                    amount,
                    ArenaProviderOperationOutcome.TIMEOUT_BEFORE_MUTATION,
                    before,
                    before,
                    capture_attempt=attempt,
                )
                raise _provider_error(ActionControlErrorCode.PROVIDER_UNAVAILABLE, retryable=True)
            if fault is ArenaProviderFault.STATE_CHANGED_DURING_CAPTURE:
                assert self._plan.state_after_change is not None
                self._state = self._plan.state_after_change
                self._record(
                    ArenaProviderOperation.CAPTURE,
                    payment_id,
                    amount,
                    ArenaProviderOperationOutcome.STATE_CHANGED,
                    before,
                    self._state,
                    capture_attempt=attempt,
                )
                raise _provider_error(
                    ActionControlErrorCode.AUTHORITATIVE_STATE_CHANGED,
                    retryable=False,
                )

            self._state = before.model_copy(
                update={"status": PaymentStatus.CAPTURED, "captured": True}
            )
            self._applied_mutations += 1
            self._enqueue_confirmation(self._state, mutation_number=self._applied_mutations)
            if fault is ArenaProviderFault.TIMEOUT_AFTER_MUTATION:
                self._record(
                    ArenaProviderOperation.CAPTURE,
                    payment_id,
                    amount,
                    ArenaProviderOperationOutcome.TIMEOUT_AFTER_MUTATION,
                    before,
                    self._state,
                    mutation_applied=True,
                    capture_attempt=attempt,
                )
                raise _provider_error(ActionControlErrorCode.PROVIDER_UNAVAILABLE, retryable=True)
            self._record(
                ArenaProviderOperation.CAPTURE,
                payment_id,
                amount,
                ArenaProviderOperationOutcome.APPLIED,
                before,
                self._state,
                mutation_applied=True,
                capture_attempt=attempt,
            )
            return self._state

    async def drain_webhooks(self) -> tuple[RawWebhookEvent, ...]:
        """Evaluator-only delivery boundary; the returned queue is atomically consumed."""

        async with self._lock:
            drained = tuple(self._pending_webhooks)
            self._pending_webhooks.clear()
            return drained

    async def snapshot(self) -> ArenaProviderSnapshot:
        """Return evaluator evidence without exposing mutable provider internals."""

        async with self._lock:
            document = {
                "applied_mutation_count": self._applied_mutations,
                "case_id": self._plan.case_id,
                "operations": [item.model_dump(mode="json") for item in self._operations],
                "pending_webhook_count": len(self._pending_webhooks),
                "plan_sha256": self._plan.plan_sha256,
                "state": self._state.model_dump(mode="json"),
            }
            return ArenaProviderSnapshot(
                **document,
                snapshot_sha256=_canonical_hash(document),
            )

    async def close(self) -> None:
        async with self._lock:
            self._closed = True

    def _record(
        self,
        operation: ArenaProviderOperation,
        payment_id: str,
        amount: Money | None,
        outcome: ArenaProviderOperationOutcome,
        before: ProviderPaymentState,
        after: ProviderPaymentState,
        *,
        mutation_applied: bool = False,
        capture_attempt: int | None = None,
    ) -> None:
        sequence = len(self._operations) + 1
        operation_id = uuid5(
            NAMESPACE_URL,
            f"chakravyuh:arena:{self._plan.case_id}:provider-operation:{sequence}",
        )
        draft = ArenaProviderOperationReceipt.model_construct(
            operation_id=operation_id,
            sequence=sequence,
            operation=operation,
            payment_id=payment_id,
            amount=amount,
            capture_attempt=capture_attempt,
            outcome=outcome,
            mutation_applied=mutation_applied,
            state_before_sha256=_provider_state_hash(before),
            state_after_sha256=_provider_state_hash(after),
            receipt_sha256="0" * 64,
        )
        self._operations.append(
            ArenaProviderOperationReceipt.model_validate(
                {**draft.model_dump(mode="json"), "receipt_sha256": _receipt_hash(draft)}
            )
        )

    def _enqueue_confirmation(
        self,
        state: ProviderPaymentState,
        *,
        mutation_number: int,
    ) -> None:
        occurred_at = self._plan.started_at + timedelta(seconds=mutation_number)
        entity = {
            "amount": state.amount.amount_subunits,
            "captured": state.captured,
            "currency": state.amount.currency,
            "entity": "payment",
            "id": state.payment_id,
            "order_id": state.order_id,
            "status": state.status.value,
        }
        payload = {
            "account_id": self._plan.account_id,
            "contains": ["payment"],
            "created_at": int(occurred_at.timestamp()),
            "entity": "event",
            "event": "payment.captured",
            "payload": {"payment": {"entity": entity}},
        }
        body = json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode()
        source_event_id = f"arena-{self._plan.case_id}-captured-{mutation_number}"
        event = RawWebhookEvent(
            event_id=uuid5(
                NAMESPACE_URL,
                f"chakravyuh:arena:{self._plan.case_id}:webhook:{source_event_id}",
            ),
            merchant_id=self._plan.merchant_id,
            source=EventSource.RAZORPAY_WEBHOOK,
            source_event_id=source_event_id,
            event_type="payment.captured",
            account_id=self._plan.account_id,
            occurred_at=occurred_at,
            observed_at=occurred_at,
            payload=payload,
            raw_body=body,
        )
        self._pending_webhooks.extend([event] * (1 + self._plan.duplicate_confirmation_deliveries))


def create_provider_plan(
    *,
    case_id: str,
    merchant_id: str,
    account_id: str,
    initial_state: ProviderPaymentState,
    capture_fault: ArenaProviderFault = ArenaProviderFault.NONE,
    fault_on_capture_attempt: int = 1,
    state_after_change: ProviderPaymentState | None = None,
    duplicate_confirmation_deliveries: int = 0,
    started_at: datetime | None = None,
) -> ArenaProviderPlan:
    draft = ArenaProviderPlan.model_construct(
        plan_version="razorpay-twin-plan-v1",
        case_id=case_id,
        merchant_id=merchant_id,
        account_id=account_id,
        initial_state=initial_state,
        capture_fault=capture_fault,
        fault_on_capture_attempt=fault_on_capture_attempt,
        state_after_change=state_after_change,
        duplicate_confirmation_deliveries=duplicate_confirmation_deliveries,
        started_at=started_at or datetime(2026, 8, 25, tzinfo=UTC),
        plan_sha256="0" * 64,
    )
    return ArenaProviderPlan.model_validate(
        {**draft.model_dump(mode="json"), "plan_sha256": build_provider_plan_hash(draft)}
    )


def build_provider_plan_hash(plan: ArenaProviderPlan) -> str:
    return _canonical_hash(plan.model_dump(mode="json", exclude={"plan_sha256"}))


def _receipt_hash(receipt: ArenaProviderOperationReceipt) -> str:
    return _canonical_hash(receipt.model_dump(mode="json", exclude={"receipt_sha256"}))


def _snapshot_hash(snapshot: ArenaProviderSnapshot) -> str:
    return _canonical_hash(snapshot.model_dump(mode="json", exclude={"snapshot_sha256"}))


def _provider_state_hash(state: ProviderPaymentState) -> str:
    return _canonical_hash(state.model_dump(mode="json"))


def _canonical_hash(value: object) -> str:
    body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()


def _provider_error(
    code: ActionControlErrorCode,
    *,
    retryable: bool,
) -> RazorpayActionError:
    return RazorpayActionError(code, retryable=retryable)
