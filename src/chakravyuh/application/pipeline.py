"""Ordered execution of independently transactional pipeline stages."""

from dataclasses import dataclass
from typing import Protocol

from chakravyuh.application.journey_reduction import JourneyReductionBatchResult
from chakravyuh.application.normalization import NormalizationBatchResult


class NormalizationBatchProcessor(Protocol):
    async def execute(self) -> NormalizationBatchResult: ...


class JourneyReductionBatchProcessor(Protocol):
    async def execute(self) -> JourneyReductionBatchResult: ...


@dataclass(frozen=True, slots=True)
class PipelineBatchResult:
    """Committed counts across normalization and journey reduction."""

    normalization: NormalizationBatchResult
    journey_reduction: JourneyReductionBatchResult

    @property
    def claimed(self) -> int:
        return self.normalization.claimed + self.journey_reduction.claimed

    @property
    def completed(self) -> int:
        return self.normalization.completed + self.journey_reduction.completed

    @property
    def dead_lettered(self) -> int:
        return self.normalization.dead_lettered + self.journey_reduction.dead_lettered


class ProcessPipelineBatch:
    """Run normalization then reduction; each stage owns its transaction."""

    def __init__(
        self,
        normalization: NormalizationBatchProcessor,
        journey_reduction: JourneyReductionBatchProcessor,
    ) -> None:
        self._normalization = normalization
        self._journey_reduction = journey_reduction

    async def execute(self) -> PipelineBatchResult:
        normalization = await self._normalization.execute()
        journey_reduction = await self._journey_reduction.execute()
        return PipelineBatchResult(
            normalization=normalization,
            journey_reduction=journey_reduction,
        )
