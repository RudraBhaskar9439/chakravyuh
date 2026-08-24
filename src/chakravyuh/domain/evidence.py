"""Bounded, provider-backed evidence subgraphs safe for model diagnosis."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from chakravyuh.domain.enums import (
    EvidenceFactKind,
    EvidenceRelationshipType,
    IncidentRevisionReason,
    IncidentType,
)
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.incidents import IncidentLifecycle
from chakravyuh.domain.money import Money


class DiagnosisSeed(BaseModel):
    """Authoritative incident and state checkpoint selected for one diagnosis attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_revision_id: UUID
    source_revision_reason: IncidentRevisionReason
    incident: IncidentLifecycle
    state_generation: int = Field(ge=1)
    state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def generation_matches_incident(self) -> DiagnosisSeed:
        if self.incident.state_generation != self.state_generation:
            msg = "diagnosis seed generation does not match the incident checkpoint"
            raise ValueError(msg)
        return self


class GraphEvidenceFact(BaseModel):
    """One allowlisted graph fact with no raw payload or free-form provider content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=255)
    kind: EvidenceFactKind
    entity: EntityReference | None = None
    event_id: UUID | None = None
    event_type: str | None = Field(default=None, max_length=255)
    provider_status: str | None = Field(default=None, max_length=64)
    effective_payment_status: str | None = Field(default=None, max_length=64)
    amount: Money | None = None
    occurred_at: AwareDatetime | None = None
    description: str = Field(min_length=1, max_length=500)


class GraphEvidenceRelationship(BaseModel):
    """One bounded edge between citable evidence facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_evidence_id: str = Field(min_length=1, max_length=255)
    target_evidence_id: str = Field(min_length=1, max_length=255)
    relationship_type: EvidenceRelationshipType


class GraphEvidenceSnapshot(BaseModel):
    """Neo4j traversal result fenced to one projected state hash and generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=255)
    state_generation: int = Field(ge=1)
    state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_epoch: AwareDatetime
    facts: tuple[GraphEvidenceFact, ...]
    relationships: tuple[GraphEvidenceRelationship, ...]

    @model_validator(mode="after")
    def identities_and_edges_are_closed(self) -> GraphEvidenceSnapshot:
        identities = [fact.evidence_id for fact in self.facts]
        if len(identities) != len(set(identities)):
            msg = "graph evidence contains duplicate fact identities"
            raise ValueError(msg)
        known = set(identities)
        if any(
            edge.source_evidence_id not in known or edge.target_evidence_id not in known
            for edge in self.relationships
        ):
            msg = "graph evidence relationship references a missing fact"
            raise ValueError(msg)
        return self


class EvidenceSubgraph(BaseModel):
    """Canonical diagnosis input assembled from invariant facts and a fenced graph snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: UUID
    source_revision_id: UUID
    incident_type: IncidentType
    affected_entity: EntityReference
    amount_at_risk: Money | None = None
    state_generation: int = Field(ge=1)
    state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_epoch: AwareDatetime
    facts: tuple[GraphEvidenceFact, ...]
    relationships: tuple[GraphEvidenceRelationship, ...]
    assembled_at: AwareDatetime
    subgraph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def hash_and_citations_are_valid(self) -> EvidenceSubgraph:
        identities = [fact.evidence_id for fact in self.facts]
        if len(identities) != len(set(identities)):
            msg = "evidence subgraph contains duplicate fact identities"
            raise ValueError(msg)
        known = set(identities)
        if any(
            edge.source_evidence_id not in known or edge.target_evidence_id not in known
            for edge in self.relationships
        ):
            msg = "evidence subgraph relationship references a missing fact"
            raise ValueError(msg)
        if _subgraph_hash(self) != self.subgraph_hash:
            msg = "evidence subgraph hash does not match its canonical content"
            raise ValueError(msg)
        return self

    @property
    def evidence_ids(self) -> frozenset[str]:
        return frozenset(fact.evidence_id for fact in self.facts)


def build_evidence_subgraph(
    seed: DiagnosisSeed,
    graph: GraphEvidenceSnapshot,
    *,
    assembled_at: AwareDatetime,
    max_facts: int,
    max_relationships: int,
) -> EvidenceSubgraph:
    """Fence a bounded graph snapshot and add authoritative invariant evidence."""

    if not 1 <= max_facts <= 1_000 or not 0 <= max_relationships <= 5_000:
        msg = "evidence bounds are outside supported limits"
        raise ValueError(msg)
    incident = seed.incident
    if graph.merchant_id != incident.merchant_id or graph.correlation_id != incident.correlation_id:
        msg = "graph evidence belongs to another incident journey"
        raise ValueError(msg)
    if graph.state_generation != seed.state_generation or graph.state_hash != seed.state_hash:
        msg = "graph evidence is stale relative to authoritative incident state"
        raise ValueError(msg)

    invariant_facts = tuple(
        GraphEvidenceFact(
            evidence_id=evidence.evidence_id,
            kind=EvidenceFactKind.INVARIANT,
            entity=evidence.entity,
            event_id=evidence.event_id,
            description=evidence.description,
        )
        for evidence in incident.evidence
    )
    graph_ids = {fact.evidence_id for fact in graph.facts}
    if any(fact.evidence_id in graph_ids for fact in invariant_facts):
        msg = "invariant and graph facts use conflicting evidence identities"
        raise ValueError(msg)
    facts = tuple(sorted((*invariant_facts, *graph.facts), key=lambda item: item.evidence_id))
    relationships = list(graph.relationships)
    event_fact_by_id = {
        fact.event_id: fact.evidence_id
        for fact in graph.facts
        if fact.kind is EvidenceFactKind.EVENT and fact.event_id is not None
    }
    for invariant in invariant_facts:
        if invariant.event_id is None:
            continue
        target_id = event_fact_by_id.get(invariant.event_id)
        if target_id is None:
            msg = "graph evidence omits an event cited by the invariant"
            raise ValueError(msg)
        relationships.append(
            GraphEvidenceRelationship(
                source_evidence_id=invariant.evidence_id,
                target_evidence_id=target_id,
                relationship_type=EvidenceRelationshipType.SUPPORTS,
            )
        )
    relationships_tuple = tuple(
        sorted(
            relationships,
            key=lambda item: (
                item.relationship_type.value,
                item.source_evidence_id,
                item.target_evidence_id,
            ),
        )
    )
    if len(facts) > max_facts or len(relationships_tuple) > max_relationships:
        msg = "evidence subgraph exceeds configured bounds"
        raise ValueError(msg)

    draft = EvidenceSubgraph.model_construct(
        incident_id=incident.incident_id,
        source_revision_id=seed.source_revision_id,
        incident_type=incident.incident_type,
        affected_entity=incident.affected_entity,
        amount_at_risk=incident.amount_at_risk,
        state_generation=seed.state_generation,
        state_hash=seed.state_hash,
        projection_epoch=graph.projection_epoch,
        facts=facts,
        relationships=relationships_tuple,
        assembled_at=assembled_at,
        subgraph_hash="0" * 64,
    )
    return EvidenceSubgraph(
        incident_id=incident.incident_id,
        source_revision_id=seed.source_revision_id,
        incident_type=incident.incident_type,
        affected_entity=incident.affected_entity,
        amount_at_risk=incident.amount_at_risk,
        state_generation=seed.state_generation,
        state_hash=seed.state_hash,
        projection_epoch=graph.projection_epoch,
        facts=facts,
        relationships=relationships_tuple,
        assembled_at=assembled_at,
        subgraph_hash=_subgraph_hash(draft),
    )


def _subgraph_hash(subgraph: EvidenceSubgraph) -> str:
    values = subgraph.model_dump(mode="json", exclude={"subgraph_hash"})
    return _hash(values)


def _hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()
