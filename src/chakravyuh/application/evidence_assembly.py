"""Build bounded diagnosis evidence from a fenced Neo4j projection."""

from datetime import UTC, datetime

from chakravyuh.application.ports import GraphEvidenceReader
from chakravyuh.domain.errors import (
    DiagnosisErrorCode,
    DiagnosisProcessingError,
)
from chakravyuh.domain.evidence import DiagnosisSeed, EvidenceSubgraph, build_evidence_subgraph


class AssembleEvidenceSubgraph:
    """Require graph evidence to match the authoritative incident state checkpoint."""

    def __init__(
        self,
        reader: GraphEvidenceReader,
        *,
        max_facts: int,
        max_relationships: int,
    ) -> None:
        self._reader = reader
        self._max_facts = max_facts
        self._max_relationships = max_relationships

    async def assemble(self, seed: DiagnosisSeed) -> EvidenceSubgraph:
        graph_fact_budget = self._max_facts - len(seed.incident.evidence)
        if graph_fact_budget < 1:
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.EVIDENCE_TOO_LARGE,
                retryable=False,
            )
        graph = await self._reader.snapshot(
            seed,
            max_facts=graph_fact_budget,
            max_relationships=self._max_relationships,
        )
        try:
            return build_evidence_subgraph(
                seed,
                graph,
                assembled_at=datetime.now(UTC),
                max_facts=self._max_facts,
                max_relationships=self._max_relationships,
            )
        except ValueError as failure:
            message = str(failure)
            if "stale" in message:
                raise DiagnosisProcessingError(
                    DiagnosisErrorCode.GRAPH_STALE,
                    retryable=True,
                ) from failure
            if "exceeds" in message or "bounds" in message:
                raise DiagnosisProcessingError(
                    DiagnosisErrorCode.EVIDENCE_TOO_LARGE,
                    retryable=False,
                ) from failure
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.EVIDENCE_INCOMPLETE,
                retryable=True,
            ) from failure
