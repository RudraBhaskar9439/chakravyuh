"""Ordered execution of independently transactional pipeline stages."""

from dataclasses import dataclass
from typing import Protocol

from chakravyuh.application.invariant_evaluation import InvariantEvaluationBatchResult
from chakravyuh.application.journey_reduction import JourneyReductionBatchResult
from chakravyuh.application.normalization import NormalizationBatchResult


class NormalizationBatchProcessor(Protocol):
    async def execute(self) -> NormalizationBatchResult: ...


class JourneyReductionBatchProcessor(Protocol):
    async def execute(self) -> JourneyReductionBatchResult: ...


class InvariantEvaluationBatchProcessor(Protocol):
    async def execute(self) -> InvariantEvaluationBatchResult: ...


@dataclass(frozen=True, slots=True)
class PipelineBatchResult:
    """Committed counts across independently transactional pipeline stages."""

    normalization: NormalizationBatchResult
    journey_reduction: JourneyReductionBatchResult
    invariant_evaluation: InvariantEvaluationBatchResult

    @property
    def claimed(self) -> int:
        return (
            self.normalization.claimed
            + self.journey_reduction.claimed
            + self.invariant_evaluation.claimed
        )

    @property
    def completed(self) -> int:
        return (
            self.normalization.completed
            + self.journey_reduction.completed
            + self.invariant_evaluation.completed
        )

    @property
    def dead_lettered(self) -> int:
        return (
            self.normalization.dead_lettered
            + self.journey_reduction.dead_lettered
            + self.invariant_evaluation.dead_lettered
        )


class ProcessPipelineBatch:
    """Run ingestion, reduction, and invariants; each stage owns its transaction."""

    def __init__(
        self,
        normalization: NormalizationBatchProcessor,
        journey_reduction: JourneyReductionBatchProcessor,
        invariant_evaluation: InvariantEvaluationBatchProcessor,
    ) -> None:
        self._normalization = normalization
        self._journey_reduction = journey_reduction
        self._invariant_evaluation = invariant_evaluation

    async def execute(self) -> PipelineBatchResult:
        normalization = await self._normalization.execute()
        journey_reduction = await self._journey_reduction.execute()
        invariant_evaluation = await self._invariant_evaluation.execute()
        return PipelineBatchResult(
            normalization=normalization,
            journey_reduction=journey_reduction,
            invariant_evaluation=invariant_evaluation,
        )
