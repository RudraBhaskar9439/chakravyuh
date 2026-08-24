"""Leased, at-least-once orchestration for the rebuildable graph."""

from dataclasses import dataclass

from chakravyuh.application.ports import GraphProjectionRepository, GraphProjector
from chakravyuh.domain.errors import ProjectionLeaseLostError, StaleGraphProjectionError


@dataclass(frozen=True, slots=True)
class GraphProjectionBatchResult:
    claimed: int = 0
    completed: int = 0
    retried: int = 0
    dead_lettered: int = 0
    lease_lost: int = 0


class ProcessGraphProjectionBatch:
    """Project leased correlations and checkpoint only after Neo4j commits."""

    def __init__(
        self,
        repository: GraphProjectionRepository,
        projector: GraphProjector,
        *,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
        max_failures: int,
        retry_delay_seconds: float,
    ) -> None:
        self._repository = repository
        self._projector = projector
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._max_failures = max_failures
        self._retry_delay_seconds = retry_delay_seconds

    async def execute(self) -> GraphProjectionBatchResult:
        claims = await self._repository.claim_batch(
            worker_id=self._worker_id,
            batch_size=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        completed = 0
        retried = 0
        dead_lettered = 0
        lease_lost = 0
        for claim in claims:
            try:
                projection = await self._repository.load(claim)
                receipt = await self._projector.project(projection)
            except Exception as failure:
                try:
                    is_dead_letter = await self._repository.fail(
                        claim,
                        error_code=_projection_error_code(failure),
                        max_failures=self._max_failures,
                        retry_delay_seconds=self._retry_delay_seconds,
                    )
                except ProjectionLeaseLostError:
                    lease_lost += 1
                    continue
                dead_lettered += int(is_dead_letter)
                retried += int(not is_dead_letter)
            else:
                try:
                    await self._repository.complete(claim, receipt)
                except ProjectionLeaseLostError:
                    lease_lost += 1
                    continue
                completed += 1
        return GraphProjectionBatchResult(
            claimed=len(claims),
            completed=completed,
            retried=retried,
            dead_lettered=dead_lettered,
            lease_lost=lease_lost,
        )


def _projection_error_code(failure: Exception) -> str:
    """Map exceptions to stable codes without storing messages or payloads."""

    module = type(failure).__module__
    name = type(failure).__name__
    if module.startswith("neo4j") and name in {
        "ServiceUnavailable",
        "SessionExpired",
        "TransientError",
    }:
        return "neo4j_unavailable"
    if module.startswith("neo4j"):
        return "neo4j_projection_rejected"
    if isinstance(failure, StaleGraphProjectionError):
        return "neo4j_stale_generation"
    return "projection_internal_error"
