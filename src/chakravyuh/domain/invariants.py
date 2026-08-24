"""Deterministic, time-aware payment invariants and explainable findings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from chakravyuh.domain.enums import EntityType, IncidentType, PaymentStatus
from chakravyuh.domain.events import EntityReference, NormalizedEvent
from chakravyuh.domain.incidents import IncidentEvidence
from chakravyuh.domain.journeys import JourneyEntityState, PaymentJourneyState
from chakravyuh.domain.money import Money

INVARIANT_ENGINE_VERSION = "payment-invariants-v1"
_ACTIVE_PAYMENT_LINK_STATUSES = frozenset({"active", "created", "issued"})
_CAPTURED_STATUSES = frozenset(
    {
        PaymentStatus.CAPTURED,
        PaymentStatus.PARTIALLY_REFUNDED,
        PaymentStatus.REFUNDED,
    }
)


class InvariantPolicy(BaseModel):
    """Versioned time windows that suppress expected asynchronous transitions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    captured_order_paid_grace_seconds: int = Field(default=300, ge=1, le=86_400)
    authorized_capture_grace_seconds: int = Field(default=900, ge=1, le=86_400)
    failed_recovery_grace_seconds: int = Field(default=1_800, ge=1, le=604_800)
    stale_recovery_link_grace_seconds: int = Field(default=300, ge=1, le=86_400)

    @property
    def version(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return f"{INVARIANT_ENGINE_VERSION}-{hashlib.sha256(canonical).hexdigest()[:12]}"


class InvariantFinding(BaseModel):
    """One rule result with stable identity and only verifiable evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    finding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_id: str = Field(min_length=1, max_length=64)
    rule_version: str = Field(min_length=1, max_length=64)
    merchant_id: str = Field(min_length=1, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=255)
    incident_type: IncidentType
    affected_entity: EntityReference
    amount_at_risk: Money | None = None
    evidence: tuple[IncidentEvidence, ...] = ()


class InvariantEvaluationResult(BaseModel):
    """Complete findings plus the earliest time-dependent re-evaluation deadline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluator_version: str = Field(min_length=1, max_length=64)
    evaluated_at: AwareDatetime
    findings: tuple[InvariantFinding, ...]
    next_evaluation_at: AwareDatetime | None = None


class DeterministicPaymentInvariantEvaluator:
    """Evaluate allowlisted rules without model inference or graph authority."""

    def __init__(self, policy: InvariantPolicy | None = None) -> None:
        self.policy = policy or InvariantPolicy()
        self.version = self.policy.version

    def evaluate(
        self,
        state: PaymentJourneyState,
        events: tuple[NormalizedEvent, ...],
        *,
        as_of: AwareDatetime,
    ) -> InvariantEvaluationResult:
        entities = {
            (item.entity.entity_type, item.entity.entity_id): item for item in state.entities
        }
        findings: list[InvariantFinding] = []
        deadlines: list[AwareDatetime] = []
        findings.extend(self._captured_order_unpaid(state, entities, as_of, deadlines))
        findings.extend(self._authorized_not_captured(state, as_of, deadlines))
        findings.extend(self._failed_without_recovery(state, as_of, deadlines))
        findings.extend(self._stale_recovery_links(state, entities, as_of, deadlines))
        findings.extend(self._duplicate_recovery_links(state))
        findings.extend(self._event_order_corruption(state, events))
        return InvariantEvaluationResult(
            evaluator_version=self.version,
            evaluated_at=as_of,
            findings=tuple(
                sorted(
                    findings,
                    key=lambda item: (
                        item.incident_type.value,
                        item.affected_entity.entity_type.value,
                        item.affected_entity.entity_id,
                    ),
                )
            ),
            next_evaluation_at=min(deadlines) if deadlines else None,
        )

    def _captured_order_unpaid(
        self,
        state: PaymentJourneyState,
        entities: dict[tuple[EntityType, str], JourneyEntityState],
        as_of: AwareDatetime,
        deadlines: list[AwareDatetime],
    ) -> list[InvariantFinding]:
        results: list[InvariantFinding] = []
        grace = timedelta(seconds=self.policy.captured_order_paid_grace_seconds)
        for payment in _entities_of_type(state, EntityType.PAYMENT):
            if (
                payment.effective_payment_status not in _CAPTURED_STATUSES
                or payment.order_id is None
            ):
                continue
            order = entities.get((EntityType.RAZORPAY_ORDER, payment.order_id))
            if order is not None and order.provider_status == "paid":
                continue
            deadline = payment.last_occurred_at + grace
            if as_of < deadline:
                deadlines.append(deadline)
                continue
            evidence = [
                _evidence(
                    "captured-payment",
                    payment,
                    "Payment has provider-backed captured value.",
                )
            ]
            if order is not None:
                evidence.append(
                    _evidence(
                        "order-not-paid",
                        order,
                        "Referenced Razorpay order is not in paid state.",
                    )
                )
            results.append(
                self._finding(
                    state,
                    rule_id="captured-order-unpaid",
                    incident_type=IncidentType.CAPTURED_BUT_ORDER_UNPAID,
                    affected=payment,
                    amount=payment.amount,
                    evidence=evidence,
                )
            )
        return results

    def _authorized_not_captured(
        self,
        state: PaymentJourneyState,
        as_of: AwareDatetime,
        deadlines: list[AwareDatetime],
    ) -> list[InvariantFinding]:
        results: list[InvariantFinding] = []
        grace = timedelta(seconds=self.policy.authorized_capture_grace_seconds)
        for payment in _entities_of_type(state, EntityType.PAYMENT):
            if payment.effective_payment_status is not PaymentStatus.AUTHORIZED:
                continue
            deadline = payment.last_occurred_at + grace
            if as_of < deadline:
                deadlines.append(deadline)
                continue
            results.append(
                self._finding(
                    state,
                    rule_id="authorized-not-captured",
                    incident_type=IncidentType.AUTHORIZED_NOT_CAPTURED,
                    affected=payment,
                    amount=payment.amount,
                    evidence=(
                        _evidence(
                            "authorization-open",
                            payment,
                            "Payment remains authorized beyond the configured capture window.",
                        ),
                    ),
                )
            )
        return results

    def _failed_without_recovery(
        self,
        state: PaymentJourneyState,
        as_of: AwareDatetime,
        deadlines: list[AwareDatetime],
    ) -> list[InvariantFinding]:
        payments = list(_entities_of_type(state, EntityType.PAYMENT))
        captured_times = [
            payment.last_occurred_at
            for payment in payments
            if payment.effective_payment_status in _CAPTURED_STATUSES
        ]
        grace = timedelta(seconds=self.policy.failed_recovery_grace_seconds)
        results: list[InvariantFinding] = []
        for payment in payments:
            if payment.effective_payment_status is not PaymentStatus.FAILED:
                continue
            if any(captured_at > payment.last_occurred_at for captured_at in captured_times):
                continue
            deadline = payment.last_occurred_at + grace
            if as_of < deadline:
                deadlines.append(deadline)
                continue
            results.append(
                self._finding(
                    state,
                    rule_id="failed-without-recovery",
                    incident_type=IncidentType.FAILED_WITHOUT_RECOVERY,
                    affected=payment,
                    amount=payment.amount,
                    evidence=(
                        _evidence(
                            "failed-payment",
                            payment,
                            "Failed payment has no later captured payment in this journey.",
                        ),
                    ),
                )
            )
        return results

    def _stale_recovery_links(
        self,
        state: PaymentJourneyState,
        entities: dict[tuple[EntityType, str], JourneyEntityState],
        as_of: AwareDatetime,
        deadlines: list[AwareDatetime],
    ) -> list[InvariantFinding]:
        grace = timedelta(seconds=self.policy.stale_recovery_link_grace_seconds)
        results: list[InvariantFinding] = []
        for link in _active_payment_links(state):
            if link.order_id is None:
                continue
            order = entities.get((EntityType.RAZORPAY_ORDER, link.order_id))
            if order is None or order.provider_status != "paid":
                continue
            deadline = order.last_occurred_at + grace
            if as_of < deadline:
                deadlines.append(deadline)
                continue
            results.append(
                self._finding(
                    state,
                    rule_id="stale-recovery-after-success",
                    incident_type=IncidentType.STALE_RECOVERY_AFTER_SUCCESS,
                    affected=link,
                    amount=link.amount,
                    evidence=(
                        _evidence("paid-order", order, "Referenced order is paid."),
                        _evidence(
                            "active-recovery-link",
                            link,
                            "Recovery payment link remains active after order success.",
                        ),
                    ),
                )
            )
        return results

    def _duplicate_recovery_links(self, state: PaymentJourneyState) -> list[InvariantFinding]:
        by_order: dict[str, list[JourneyEntityState]] = {}
        for link in _active_payment_links(state):
            if link.order_id is not None:
                by_order.setdefault(link.order_id, []).append(link)
        results: list[InvariantFinding] = []
        for links in by_order.values():
            if len(links) < 2:
                continue
            links.sort(key=lambda item: item.entity.entity_id)
            affected = links[0]
            results.append(
                self._finding(
                    state,
                    rule_id="duplicate-active-recovery-links",
                    incident_type=IncidentType.DUPLICATE_ACTIVE_RECOVERY_LINKS,
                    affected=affected,
                    amount=affected.amount,
                    evidence=tuple(
                        _evidence(
                            "active-link",
                            link,
                            "Multiple active recovery links reference the same order.",
                        )
                        for link in links
                    ),
                )
            )
        return results

    def _event_order_corruption(
        self,
        state: PaymentJourneyState,
        events: tuple[NormalizedEvent, ...],
    ) -> list[InvariantFinding]:
        by_payment: dict[str, list[NormalizedEvent]] = {}
        for event in events:
            if event.subject.entity_type is EntityType.PAYMENT:
                by_payment.setdefault(event.subject.entity_id, []).append(event)
        results: list[InvariantFinding] = []
        for payment_id, payment_events in by_payment.items():
            ordered = sorted(
                payment_events,
                key=lambda event: (
                    event.occurred_at,
                    event.observed_at,
                    event.event_type,
                    event.source_event_id,
                    event.event_id.hex,
                ),
            )
            captured: NormalizedEvent | None = None
            regression: NormalizedEvent | None = None
            for event in ordered:
                status = _event_status(event)
                if status in {"captured", "partially_refunded", "refunded"}:
                    captured = event
                elif captured is not None and status in {"authorized", "created", "failed"}:
                    regression = event
                    break
            if captured is None or regression is None:
                continue
            entity = next(
                (
                    item
                    for item in _entities_of_type(state, EntityType.PAYMENT)
                    if item.entity.entity_id == payment_id
                ),
                None,
            )
            if entity is None:
                continue
            results.append(
                self._finding(
                    state,
                    rule_id="event-order-corruption",
                    incident_type=IncidentType.EVENT_ORDER_CORRUPTION,
                    affected=entity,
                    amount=entity.amount,
                    evidence=(
                        IncidentEvidence(
                            evidence_id=f"event-order-corruption:{captured.event_id}:captured",
                            description="Captured event precedes a terminal-state regression.",
                            entity=captured.subject,
                            event_id=captured.event_id,
                        ),
                        IncidentEvidence(
                            evidence_id=f"event-order-corruption:{regression.event_id}:regression",
                            description=(
                                "Later event regresses the same payment from captured state."
                            ),
                            entity=regression.subject,
                            event_id=regression.event_id,
                        ),
                    ),
                )
            )
        return results

    def _finding(
        self,
        state: PaymentJourneyState,
        *,
        rule_id: str,
        incident_type: IncidentType,
        affected: JourneyEntityState,
        amount: Money | None,
        evidence: Iterable[IncidentEvidence],
    ) -> InvariantFinding:
        evidence_tuple = tuple(evidence)
        identity = {
            "merchant_id": state.merchant_id,
            "correlation_id": state.correlation_id,
            "rule_id": rule_id,
            "entity_type": affected.entity.entity_type.value,
            "entity_id": affected.entity.entity_id,
        }
        incident_key = _hash(identity)
        finding = {
            **identity,
            "incident_type": incident_type.value,
            "amount_at_risk": None if amount is None else amount.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence_tuple],
            "rule_version": self.version,
        }
        return InvariantFinding(
            incident_key=incident_key,
            finding_hash=_hash(finding),
            rule_id=rule_id,
            rule_version=self.version,
            merchant_id=state.merchant_id,
            correlation_id=state.correlation_id,
            incident_type=incident_type,
            affected_entity=affected.entity,
            amount_at_risk=amount,
            evidence=evidence_tuple,
        )


def _entities_of_type(
    state: PaymentJourneyState,
    entity_type: EntityType,
) -> Iterable[JourneyEntityState]:
    return (item for item in state.entities if item.entity.entity_type is entity_type)


def _active_payment_links(state: PaymentJourneyState) -> list[JourneyEntityState]:
    return [
        item
        for item in _entities_of_type(state, EntityType.PAYMENT_LINK)
        if item.provider_status in _ACTIVE_PAYMENT_LINK_STATUSES
    ]


def _event_status(event: NormalizedEvent) -> str:
    payload_status = event.payload.get("status")
    if isinstance(payload_status, str) and payload_status:
        return payload_status
    return event.event_type.rpartition(".")[2]


def _evidence(
    fact: str,
    entity: JourneyEntityState,
    description: str,
) -> IncidentEvidence:
    return IncidentEvidence(
        evidence_id=f"{fact}:{entity.entity.entity_type.value}:{entity.entity.entity_id}",
        description=description,
        entity=entity.entity,
        event_id=entity.latest_event_id,
    )


def _hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()
