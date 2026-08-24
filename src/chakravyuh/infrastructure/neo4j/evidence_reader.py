"""Bounded, read-only Neo4j evidence traversal for one incident journey."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from chakravyuh.config import Settings
from chakravyuh.domain.enums import (
    EntityType,
    EvidenceFactKind,
    EvidenceRelationshipType,
)
from chakravyuh.domain.errors import DiagnosisErrorCode, DiagnosisProcessingError
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.evidence import (
    DiagnosisSeed,
    GraphEvidenceFact,
    GraphEvidenceRelationship,
    GraphEvidenceSnapshot,
)
from chakravyuh.domain.money import Money


class Neo4jEvidenceReader:
    """Read only allowlisted graph properties and reject truncation or projection lag."""

    def __init__(self, settings: Settings, *, driver: AsyncDriver | None = None) -> None:
        self._database = settings.neo4j_database
        self._driver = driver or AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password.get_secret_value()),
            connection_timeout=settings.neo4j_connection_timeout_seconds,
        )

    async def snapshot(
        self,
        seed: DiagnosisSeed,
        *,
        max_facts: int,
        max_relationships: int,
    ) -> GraphEvidenceSnapshot:
        if not 1 <= max_facts <= 1_000 or not 0 <= max_relationships <= 5_000:
            msg = "evidence bounds are outside supported limits"
            raise ValueError(msg)
        try:
            return await self._read_snapshot(
                seed,
                max_facts=max_facts,
                max_relationships=max_relationships,
            )
        except DiagnosisProcessingError:
            raise
        except Exception as failure:
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.GRAPH_UNAVAILABLE,
                retryable=True,
            ) from failure

    async def _read_snapshot(
        self,
        seed: DiagnosisSeed,
        *,
        max_facts: int,
        max_relationships: int,
    ) -> GraphEvidenceSnapshot:
        incident = seed.incident
        parameters: dict[str, Any] = {
            "merchant_id": incident.merchant_id,
            "correlation_id": incident.correlation_id,
            "fact_limit": max_facts + 1,
            "relationship_limit": max_relationships + 1,
        }
        async with self._driver.session(database=self._database) as session:
            journey_result = await session.run(
                """
                MATCH (journey:PaymentJourney {
                    merchant_id: $merchant_id,
                    correlation_id: $correlation_id
                })
                RETURN journey
                """,
                **parameters,
            )
            journey_record = await journey_result.single()
            if journey_record is None:
                raise DiagnosisProcessingError(
                    DiagnosisErrorCode.GRAPH_STALE,
                    retryable=True,
                )
            journey = dict(journey_record["journey"])
            entity_rows = await _records(
                session,
                """
                MATCH (journey:PaymentJourney {
                    merchant_id: $merchant_id,
                    correlation_id: $correlation_id
                })-[:CONTAINS]->(entity:FinancialEntity)
                RETURN entity
                ORDER BY entity.key
                LIMIT $fact_limit
                """,
                parameters,
            )
            event_rows = await _records(
                session,
                """
                MATCH (journey:PaymentJourney {
                    merchant_id: $merchant_id,
                    correlation_id: $correlation_id
                })-[:HAS_EVENT]->(event:MoneyEvent)
                RETURN event
                ORDER BY event.occurred_at, event.event_id
                LIMIT $fact_limit
                """,
                parameters,
            )
            relationship_rows = await _records(
                session,
                """
                MATCH (journey:PaymentJourney {
                    merchant_id: $merchant_id,
                    correlation_id: $correlation_id
                })
                CALL (journey) {
                    MATCH (journey)-[:CONTAINS]->(source:FinancialEntity)
                    RETURN 'contains' AS kind, journey.key AS source_key, source.key AS target_key
                    UNION ALL
                    MATCH (journey)-[:HAS_EVENT]->(source:MoneyEvent)
                    RETURN 'has_event' AS kind, journey.key AS source_key, source.key AS target_key
                    UNION ALL
                    MATCH (journey)-[:HAS_EVENT]->(source:MoneyEvent)
                    MATCH (source)-[edge:DESCRIBES]->(target:FinancialEntity)
                    WHERE edge.journey_key = journey.key
                    RETURN 'describes' AS kind, source.key AS source_key, target.key AS target_key
                    UNION ALL
                    MATCH (journey)-[:CONTAINS]->(source:FinancialEntity)
                    MATCH (source)-[edge:RELATES_TO]->(target:FinancialEntity)
                    WHERE edge.journey_key = journey.key
                    RETURN edge.kind AS kind, source.key AS source_key, target.key AS target_key
                }
                RETURN kind, source_key, target_key
                ORDER BY kind, source_key, target_key
                LIMIT $relationship_limit
                """,
                parameters,
            )

        facts = (
            _journey_fact(journey),
            *(_entity_fact(dict(row["entity"])) for row in entity_rows),
            *(_event_fact(dict(row["event"])) for row in event_rows),
        )
        if len(facts) > max_facts or len(relationship_rows) > max_relationships:
            raise DiagnosisProcessingError(
                DiagnosisErrorCode.EVIDENCE_TOO_LARGE,
                retryable=False,
            )
        relationships = tuple(
            GraphEvidenceRelationship(
                source_evidence_id=_evidence_id(row["source_key"], kind=row["kind"]),
                target_evidence_id=_evidence_id(row["target_key"], kind=row["kind"], target=True),
                relationship_type=EvidenceRelationshipType(row["kind"]),
            )
            for row in relationship_rows
        )
        return GraphEvidenceSnapshot(
            merchant_id=incident.merchant_id,
            correlation_id=incident.correlation_id,
            state_generation=int(journey["state_generation"]),
            state_hash=str(journey["state_hash"]),
            projection_epoch=datetime.fromisoformat(str(journey["projection_epoch"])),
            facts=facts,
            relationships=relationships,
        )

    async def close(self) -> None:
        await self._driver.close()


async def _records(session: Any, query: str, parameters: dict[str, Any]) -> list[Any]:
    result = await session.run(query, **parameters)
    return [record async for record in result]


def _journey_fact(properties: dict[str, Any]) -> GraphEvidenceFact:
    return GraphEvidenceFact(
        evidence_id=f"journey:{properties['key']}",
        kind=EvidenceFactKind.JOURNEY,
        occurred_at=datetime.fromisoformat(str(properties["last_occurred_at"])),
        description="Projected payment journey checkpoint.",
    )


def _entity_fact(properties: dict[str, Any]) -> GraphEvidenceFact:
    entity = EntityReference(
        entity_type=EntityType(properties["entity_type"]),
        entity_id=properties["provider_id"],
    )
    amount = _money(properties)
    occurred = properties.get("last_occurred_at")
    return GraphEvidenceFact(
        evidence_id=f"entity:{properties['key']}",
        kind=EvidenceFactKind.ENTITY,
        entity=entity,
        provider_status=properties.get("provider_status"),
        effective_payment_status=properties.get("effective_payment_status"),
        amount=amount,
        occurred_at=None if occurred is None else datetime.fromisoformat(str(occurred)),
        description="Current projected financial entity state.",
    )


def _event_fact(properties: dict[str, Any]) -> GraphEvidenceFact:
    return GraphEvidenceFact(
        evidence_id=f"event:{properties['key']}",
        kind=EvidenceFactKind.EVENT,
        event_id=properties["event_id"],
        event_type=properties["event_type"],
        occurred_at=datetime.fromisoformat(str(properties["occurred_at"])),
        description="Normalized event evidence.",
    )


def _money(properties: dict[str, Any]) -> Money | None:
    amount = properties.get("amount_subunits")
    currency = properties.get("currency")
    if not isinstance(amount, int) or not isinstance(currency, str):
        return None
    return Money(amount_subunits=amount, currency=currency)


def _evidence_id(key: str, *, kind: str, target: bool = False) -> str:
    if kind in {"contains", "has_event"} and not target:
        return f"journey:{key}"
    if kind == "has_event" or (kind == "describes" and not target):
        return f"event:{key}"
    return f"entity:{key}"
