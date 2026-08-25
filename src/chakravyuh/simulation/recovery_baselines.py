"""Oracle-isolated no-intervention and naive retry-all recovery baselines."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chakravyuh.application.ports import RazorpayPaymentGateway
from chakravyuh.domain.enums import ActionType, EntityType
from chakravyuh.domain.errors import RazorpayActionError
from chakravyuh.domain.journeys import JourneyEntityState, reduce_payment_journey
from chakravyuh.domain.recovery_arena import ArenaStrategyName, RecoveryArenaContract
from chakravyuh.simulation.razorpay_twin import DeterministicRazorpayTwin
from chakravyuh.simulation.recovery_portfolio import (
    ArenaEvaluationCase,
    ArenaObservedCase,
    RecoveryPortfolio,
)


class ArenaStrategyObservation(BaseModel):
    """What a strategy did and observed, before evaluator-owned scoring."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: ArenaStrategyName
    case_id: str
    action_attempted: bool
    action_type: ActionType | None = None
    target_payment_id: str | None = None
    provider_returned_success: bool
    stable_error_code: str | None = None


class ArenaStrategy(Protocol):
    name: ArenaStrategyName

    async def run(
        self,
        observed: ArenaObservedCase,
        gateway: RazorpayPaymentGateway,
    ) -> ArenaStrategyObservation: ...


class NoInterventionStrategy:
    name = ArenaStrategyName.NO_INTERVENTION

    async def run(
        self,
        observed: ArenaObservedCase,
        gateway: RazorpayPaymentGateway,
    ) -> ArenaStrategyObservation:
        del gateway
        return ArenaStrategyObservation(
            strategy=self.name,
            case_id=observed.case_id,
            action_attempted=False,
            provider_returned_success=False,
        )


class RetryAllStrategy:
    """Intentionally unsafe baseline: capture every latest uncaptured payment."""

    name = ArenaStrategyName.RETRY_ALL

    async def run(
        self,
        observed: ArenaObservedCase,
        gateway: RazorpayPaymentGateway,
    ) -> ArenaStrategyObservation:
        payment = _latest_payment(observed)
        try:
            current = await gateway.fetch_payment(payment.entity.entity_id)
        except RazorpayActionError as failure:
            return _observation(
                self.name,
                observed,
                payment_id=payment.entity.entity_id,
                action_attempted=False,
                provider_returned_success=False,
                error_code=failure.code.value,
            )
        if current.captured:
            return _observation(
                self.name,
                observed,
                payment_id=current.payment_id,
                action_attempted=False,
                provider_returned_success=True,
            )
        try:
            await gateway.capture_payment(current.payment_id, current.amount)
        except RazorpayActionError as failure:
            return _observation(
                self.name,
                observed,
                payment_id=current.payment_id,
                action_attempted=True,
                provider_returned_success=False,
                error_code=failure.code.value,
            )
        return _observation(
            self.name,
            observed,
            payment_id=current.payment_id,
            action_attempted=True,
            provider_returned_success=True,
        )


class ArenaScoredCaseResult(BaseModel):
    """Evaluator-owned case score binding observation, oracle, provider state, and confirmation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    strategy: ArenaStrategyName
    action_attempted: bool
    provider_returned_success: bool
    provider_confirmed: bool
    confirmed_recovery: bool
    incorrect_action: bool
    recoverable_missed: bool
    stable_error_code: str | None = None
    provider_operation_count: int = Field(ge=0)
    applied_mutation_count: int = Field(ge=0)
    recovered_subunits: int = Field(ge=0)
    incorrect_action_cost_subunits: int = Field(ge=0)
    provider_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_result(self) -> ArenaScoredCaseResult:
        if self.confirmed_recovery and not self.provider_confirmed:
            msg = "arena recovery requires provider confirmation"
            raise ValueError(msg)
        if _model_hash(self, exclude={"result_sha256"}) != self.result_sha256:
            msg = "arena scored-result hash does not match its canonical content"
            raise ValueError(msg)
        return self


class ArenaStrategyMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: ArenaStrategyName
    case_count: int = Field(ge=1)
    oracle_recoverable_count: int = Field(ge=0)
    action_attempt_count: int = Field(ge=0)
    provider_confirmed_count: int = Field(ge=0)
    confirmed_recovery_count: int = Field(ge=0)
    incorrect_action_count: int = Field(ge=0)
    missed_recoverable_count: int = Field(ge=0)
    provider_operation_count: int = Field(ge=0)
    applied_mutation_count: int = Field(ge=0)
    duplicate_mutation_count: int = Field(ge=0)
    oracle_recoverable_revenue_subunits: int = Field(ge=0)
    confirmed_recovered_revenue_subunits: int = Field(ge=0)
    incorrect_action_cost_subunits: int = Field(ge=0)
    net_recovery_value_subunits: int
    recovery_efficiency: float = Field(ge=0, le=1)
    results_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArenaBaselineReport(BaseModel):
    """Reproducible aggregate comparison with result roots instead of cherry-picked examples."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: str = "recovery-arena-baselines-v1"
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    portfolio_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategies: tuple[ArenaStrategyMetrics, ...]
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool

    @model_validator(mode="after")
    def validate_report(self) -> ArenaBaselineReport:
        if tuple(item.strategy for item in self.strategies) != (
            ArenaStrategyName.NO_INTERVENTION,
            ArenaStrategyName.RETRY_ALL,
        ):
            msg = "arena baseline report requires canonical no-intervention and retry-all order"
            raise ValueError(msg)
        if self.passed != _baseline_passed(self.strategies):
            msg = "arena baseline pass flag must match its proof gates"
            raise ValueError(msg)
        if _model_hash(self, exclude={"report_sha256"}) != self.report_sha256:
            msg = "arena baseline report hash does not match its canonical content"
            raise ValueError(msg)
        return self


async def run_baseline_tournament(
    portfolio: RecoveryPortfolio,
    contract: RecoveryArenaContract,
) -> tuple[ArenaBaselineReport, tuple[ArenaScoredCaseResult, ...]]:
    all_results: list[ArenaScoredCaseResult] = []
    metrics: list[ArenaStrategyMetrics] = []
    for strategy in (NoInterventionStrategy(), RetryAllStrategy()):
        strategy_results = tuple(
            [await _evaluate_case(item, strategy, contract) for item in portfolio.cases]
        )
        all_results.extend(strategy_results)
        metrics.append(_aggregate(strategy.name, strategy_results, portfolio))
    passed = _baseline_passed(tuple(metrics))
    draft = ArenaBaselineReport.model_construct(
        report_version="recovery-arena-baselines-v1",
        contract_sha256=contract.contract_sha256,
        portfolio_manifest_sha256=portfolio.manifest.manifest_sha256,
        strategies=tuple(metrics),
        report_sha256="0" * 64,
        passed=passed,
    )
    report = ArenaBaselineReport.model_validate(
        {
            **draft.model_dump(mode="json"),
            "report_sha256": _model_hash(draft, exclude={"report_sha256"}),
        }
    )
    return report, tuple(all_results)


async def _evaluate_case(
    case: ArenaEvaluationCase,
    strategy: ArenaStrategy,
    contract: RecoveryArenaContract,
) -> ArenaScoredCaseResult:
    twin = DeterministicRazorpayTwin(case.oracle.provider_plan)
    observation = await strategy.run(case.observed, twin.strategy_gateway())
    webhooks = await twin.drain_webhooks()
    snapshot = await twin.snapshot()
    confirmations = {
        item.source_event_id
        for item in webhooks
        if item.event_type in contract.confirmation_event_types
    }
    provider_confirmed = bool(confirmations)
    confirmed_recovery = case.oracle.recoverable and provider_confirmed
    incorrect_action = observation.action_attempted and not case.oracle.action_eligible
    recoverable_missed = case.oracle.recoverable and not confirmed_recovery
    recovered_subunits = case.oracle.payment_amount.amount_subunits if confirmed_recovery else 0
    incorrect_cost = contract.incorrect_action_cost_subunits if incorrect_action else 0
    draft = ArenaScoredCaseResult.model_construct(
        case_id=case.observed.case_id,
        strategy=strategy.name,
        action_attempted=observation.action_attempted,
        provider_returned_success=observation.provider_returned_success,
        provider_confirmed=provider_confirmed,
        confirmed_recovery=confirmed_recovery,
        incorrect_action=incorrect_action,
        recoverable_missed=recoverable_missed,
        stable_error_code=observation.stable_error_code,
        provider_operation_count=len(snapshot.operations),
        applied_mutation_count=snapshot.applied_mutation_count,
        recovered_subunits=recovered_subunits,
        incorrect_action_cost_subunits=incorrect_cost,
        provider_snapshot_sha256=snapshot.snapshot_sha256,
        result_sha256="0" * 64,
    )
    return ArenaScoredCaseResult.model_validate(
        {
            **draft.model_dump(mode="json"),
            "result_sha256": _model_hash(draft, exclude={"result_sha256"}),
        }
    )


def _aggregate(
    strategy: ArenaStrategyName,
    results: tuple[ArenaScoredCaseResult, ...],
    portfolio: RecoveryPortfolio,
) -> ArenaStrategyMetrics:
    recoverable_count = sum(item.oracle.recoverable for item in portfolio.cases)
    recovered = sum(item.recovered_subunits for item in results)
    recoverable_revenue = portfolio.manifest.oracle_recoverable_revenue_subunits
    incorrect_cost = sum(item.incorrect_action_cost_subunits for item in results)
    return ArenaStrategyMetrics(
        strategy=strategy,
        case_count=len(results),
        oracle_recoverable_count=recoverable_count,
        action_attempt_count=sum(item.action_attempted for item in results),
        provider_confirmed_count=sum(item.provider_confirmed for item in results),
        confirmed_recovery_count=sum(item.confirmed_recovery for item in results),
        incorrect_action_count=sum(item.incorrect_action for item in results),
        missed_recoverable_count=sum(item.recoverable_missed for item in results),
        provider_operation_count=sum(item.provider_operation_count for item in results),
        applied_mutation_count=sum(item.applied_mutation_count for item in results),
        duplicate_mutation_count=sum(max(0, item.applied_mutation_count - 1) for item in results),
        oracle_recoverable_revenue_subunits=recoverable_revenue,
        confirmed_recovered_revenue_subunits=recovered,
        incorrect_action_cost_subunits=incorrect_cost,
        net_recovery_value_subunits=recovered - incorrect_cost,
        recovery_efficiency=(1.0 if recoverable_revenue == 0 else recovered / recoverable_revenue),
        results_root_sha256=_merkle_root(sorted(item.result_sha256 for item in results)),
    )


def _latest_payment(observed: ArenaObservedCase) -> JourneyEntityState:
    state = reduce_payment_journey(list(observed.events))
    payments = [
        item
        for item in state.entities
        if item.entity.entity_type is EntityType.PAYMENT and item.amount is not None
    ]
    if not payments:
        msg = "retry-all strategy requires an observed payment"
        raise ValueError(msg)
    return max(payments, key=lambda item: (item.last_occurred_at, item.entity.entity_id))


def _baseline_passed(strategies: tuple[ArenaStrategyMetrics, ...]) -> bool:
    if len(strategies) != 2:
        return False
    no_action, retry_all = strategies
    return (
        no_action.action_attempt_count == 0
        and no_action.confirmed_recovery_count == 0
        and retry_all.duplicate_mutation_count == 0
        and retry_all.action_attempt_count > 0
    )


def _observation(
    strategy: ArenaStrategyName,
    observed: ArenaObservedCase,
    *,
    payment_id: str,
    action_attempted: bool,
    provider_returned_success: bool,
    error_code: str | None = None,
) -> ArenaStrategyObservation:
    return ArenaStrategyObservation(
        strategy=strategy,
        case_id=observed.case_id,
        action_attempted=action_attempted,
        action_type=ActionType.CAPTURE_PAYMENT if action_attempted else None,
        target_payment_id=payment_id,
        provider_returned_success=provider_returned_success,
        stable_error_code=error_code,
    )


def _model_hash(model: BaseModel, *, exclude: set[str]) -> str:
    return _canonical_hash(model.model_dump(mode="json", exclude=exclude))


def _merkle_root(hashes: Sequence[str]) -> str:
    if not hashes:
        msg = "arena result root requires at least one hash"
        raise ValueError(msg)
    layer = [bytes.fromhex(value) for value in hashes]
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [
            hashlib.sha256(layer[index] + layer[index + 1]).digest()
            for index in range(0, len(layer), 2)
        ]
    return layer[0].hex()


def _canonical_hash(value: object) -> str:
    body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()
