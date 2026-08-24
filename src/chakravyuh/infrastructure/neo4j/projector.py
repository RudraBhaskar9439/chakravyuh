"""Idempotent Neo4j projection of one complete PostgreSQL payment journey."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from neo4j import AsyncDriver, AsyncGraphDatabase

from chakravyuh.config import Settings
from chakravyuh.domain.errors import StaleGraphProjectionError
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.projections import (
    GraphProjectionInput,
    GraphProjectionReceipt,
    GraphRebuildCandidate,
    GraphRebuildReceipt,
)

_CONSTRAINTS = (
    "CREATE CONSTRAINT chakravyuh_merchant_key IF NOT EXISTS "
    "FOR (node:Merchant) REQUIRE node.key IS UNIQUE",
    "CREATE CONSTRAINT chakravyuh_journey_key IF NOT EXISTS "
    "FOR (node:PaymentJourney) REQUIRE node.key IS UNIQUE",
    "CREATE CONSTRAINT chakravyuh_entity_key IF NOT EXISTS "
    "FOR (node:FinancialEntity) REQUIRE node.key IS UNIQUE",
    "CREATE CONSTRAINT chakravyuh_event_key IF NOT EXISTS "
    "FOR (node:MoneyEvent) REQUIRE node.key IS UNIQUE",
)


class Neo4jPaymentGraphProjector:
    """Replace one journey subgraph in a retry-safe managed transaction."""

    def __init__(self, settings: Settings, *, driver: AsyncDriver | None = None) -> None:
        self._database = settings.neo4j_database
        self._driver = driver or AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password.get_secret_value()),
            connection_timeout=settings.neo4j_connection_timeout_seconds,
        )

    async def initialize_schema(self) -> None:
        async with self._driver.session(database=self._database) as session:
            for statement in _CONSTRAINTS:
                result = await session.run(statement)
                await result.consume()

    async def verify_connectivity(self) -> None:
        await self._driver.verify_connectivity()

    async def project(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        projected_at = datetime.now(UTC)
        parameters = _parameters(projection, projected_at=projected_at)
        async with self._driver.session(database=self._database) as session:
            applied = await session.execute_write(_replace_journey, parameters)
        if not applied:
            msg = "Neo4j rejected a stale journey generation"
            raise StaleGraphProjectionError(msg)
        return GraphProjectionReceipt(
            merchant_id=projection.state.merchant_id,
            correlation_id=projection.state.correlation_id,
            state_generation=projection.state_generation,
            projection_epoch=projection.projection_epoch,
            state_hash=projection.state_hash,
            entity_count=len(parameters["entities"]),
            event_count=len(parameters["events"]),
            projected_at=projected_at,
            projection_id=uuid5(
                NAMESPACE_URL,
                "chakravyuh:graph-projection:"
                f"{projection.state.merchant_id}:{projection.state.correlation_id}:"
                f"{projection.projection_epoch.isoformat()}:"
                f"{projection.state_generation}:{projection.state_hash}",
            ),
        )

    async def prune_before(self, rebuild: GraphRebuildCandidate) -> GraphRebuildReceipt:
        pruned_at = datetime.now(UTC)
        parameters = {"projection_epoch_us": _epoch_microseconds(rebuild.projection_epoch)}
        async with self._driver.session(database=self._database) as session:
            removed = await session.execute_write(_prune_before, parameters)
        return GraphRebuildReceipt(
            rebuild_id=rebuild.rebuild_id,
            projection_epoch=rebuild.projection_epoch,
            journey_count_removed=removed["journeys"],
            entity_count_removed=removed["entities"],
            event_count_removed=removed["events"],
            merchant_count_removed=removed["merchants"],
            pruned_at=pruned_at,
        )

    async def close(self) -> None:
        await self._driver.close()


async def _replace_journey(tx: Any, parameters: dict[str, Any]) -> bool:
    guard_result = await tx.run(
        """
        MERGE (journey:PaymentJourney {key: $journey_key})
        ON CREATE SET journey.state_generation = 0, journey.projection_epoch_us = 0
        WITH journey, coalesce(journey.projection_epoch_us, 0) AS current_epoch_us
        RETURN current_epoch_us < $projection_epoch_us
            OR (current_epoch_us = $projection_epoch_us
                AND journey.state_generation <= $state_generation) AS should_apply
        """,
        **parameters,
    )
    guard = await guard_result.single()
    if guard is not None and not guard["should_apply"]:
        return False
    old_result = await tx.run(
        """
        MATCH (journey:PaymentJourney {key: $journey_key})
        OPTIONAL MATCH (journey)-[:CONTAINS|HAS_EVENT]->(old)
        RETURN [node IN collect(old) WHERE node IS NOT NULL | node.key] AS old_keys
        """,
        **parameters,
    )
    old_record = await old_result.single()
    old_keys = [] if old_record is None else old_record["old_keys"]
    await _consume(
        tx,
        """
        MATCH (journey:PaymentJourney {key: $journey_key})
        MATCH (journey)-[edge:CONTAINS|HAS_EVENT]->()
        DELETE edge
        """,
        parameters,
    )
    await _consume(
        tx,
        """
        MATCH ()-[edge:RELATES_TO {journey_key: $journey_key}]->()
        DELETE edge
        """,
        parameters,
    )
    await _consume(
        tx,
        """
        MATCH ()-[edge:DESCRIBES {journey_key: $journey_key}]->()
        DELETE edge
        """,
        parameters,
    )
    await _consume(
        tx,
        """
        MERGE (merchant:Merchant {key: $merchant_key})
        SET merchant = $merchant
        MERGE (journey:PaymentJourney {key: $journey.key})
        SET journey = $journey
        MERGE (merchant)-[:OWNS]->(journey)
        """,
        parameters,
    )
    await _consume(
        tx,
        """
        MATCH (journey:PaymentJourney {key: $journey_key})
        UNWIND $entities AS item
        MERGE (entity:FinancialEntity {key: item.key})
        ON CREATE SET entity = item
        FOREACH (ignored IN CASE
            WHEN item.placeholder = false
             AND (entity.placeholder = true
               OR coalesce(item.last_occurred_epoch_ms, -1)
                  >= coalesce(entity.last_occurred_epoch_ms, -1))
            THEN [1]
            WHEN item.placeholder = true AND entity.placeholder = true THEN [1]
            ELSE []
        END | SET entity = item)
        MERGE (journey)-[:CONTAINS]->(entity)
        """,
        parameters,
    )
    await _consume(
        tx,
        """
        MATCH (journey:PaymentJourney {key: $journey_key})
        UNWIND $events AS item
        MERGE (event:MoneyEvent {key: item.key})
        SET event = item
        MERGE (journey)-[:HAS_EVENT]->(event)
        WITH event, item
        MATCH (subject:FinancialEntity {key: item.subject_key})
        MERGE (event)-[:DESCRIBES {journey_key: $journey_key}]->(subject)
        """,
        parameters,
    )
    await _consume(
        tx,
        """
        UNWIND $relationships AS item
        MATCH (source:FinancialEntity {key: item.source_key})
        MATCH (target:FinancialEntity {key: item.target_key})
        MERGE (source)-[edge:RELATES_TO {
            journey_key: $journey_key,
            kind: item.kind
        }]->(target)
        """,
        parameters,
    )
    if old_keys:
        cleanup = {**parameters, "old_keys": old_keys}
        await _consume(
            tx,
            """
            MATCH (node)
            WHERE node.key IN $old_keys
              AND (node:FinancialEntity OR node:MoneyEvent)
              AND NOT (node)<-[:CONTAINS|HAS_EVENT]-()
            DETACH DELETE node
            """,
            cleanup,
        )
    return True


async def _consume(tx: Any, statement: str, parameters: dict[str, Any]) -> None:
    result = await tx.run(statement, **parameters)
    await result.consume()


async def _prune_before(tx: Any, parameters: dict[str, Any]) -> dict[str, int]:
    return {
        "journeys": await _delete_stale_nodes(
            tx,
            """
            MATCH (node:PaymentJourney)
            WHERE coalesce(node.projection_epoch_us, 0) < $projection_epoch_us
            WITH node
            DETACH DELETE node
            RETURN count(node) AS removed
            """,
            parameters,
        ),
        "entities": await _delete_stale_nodes(
            tx,
            """
            MATCH (node:FinancialEntity)
            WHERE NOT (node)<-[:CONTAINS]-()
            WITH node
            DETACH DELETE node
            RETURN count(node) AS removed
            """,
            parameters,
        ),
        "events": await _delete_stale_nodes(
            tx,
            """
            MATCH (node:MoneyEvent)
            WHERE NOT (node)<-[:HAS_EVENT]-()
            WITH node
            DETACH DELETE node
            RETURN count(node) AS removed
            """,
            parameters,
        ),
        "merchants": await _delete_stale_nodes(
            tx,
            """
            MATCH (node:Merchant)
            WHERE NOT (node)-[:OWNS]->()
            WITH node
            DELETE node
            RETURN count(node) AS removed
            """,
            parameters,
        ),
    }


async def _delete_stale_nodes(
    tx: Any,
    statement: str,
    parameters: dict[str, Any],
) -> int:
    result = await tx.run(statement, **parameters)
    record = await result.single()
    return 0 if record is None else int(record["removed"])


def _parameters(projection: GraphProjectionInput, *, projected_at: datetime) -> dict[str, Any]:
    state = projection.state
    journey_key = _key("journey", state.merchant_id, state.correlation_id)
    entity_rows = _entity_rows(projection)
    return {
        "journey_key": journey_key,
        "state_generation": projection.state_generation,
        "projection_epoch_us": _epoch_microseconds(projection.projection_epoch),
        "merchant_key": _key("merchant", state.merchant_id),
        "merchant": {
            "key": _key("merchant", state.merchant_id),
            "merchant_id": state.merchant_id,
        },
        "journey": {
            "key": journey_key,
            "merchant_id": state.merchant_id,
            "correlation_id": state.correlation_id,
            "state_generation": projection.state_generation,
            "projection_epoch": projection.projection_epoch.isoformat(),
            "projection_epoch_us": _epoch_microseconds(projection.projection_epoch),
            "state_hash": projection.state_hash,
            "event_count": state.event_count,
            "first_occurred_at": state.first_occurred_at.isoformat(),
            "last_occurred_at": state.last_occurred_at.isoformat(),
            "projected_at": projected_at.isoformat(),
        },
        "entities": entity_rows,
        "events": [
            {
                "key": _key("event", str(event.event_id)),
                "event_id": str(event.event_id),
                "merchant_id": event.merchant_id,
                "correlation_id": event.correlation_id,
                "source": event.source.value,
                "source_event_id": event.source_event_id,
                "event_type": event.event_type,
                "subject_key": _entity_key(event.merchant_id, event.subject),
                "occurred_at": event.occurred_at.isoformat(),
                "observed_at": event.observed_at.isoformat(),
            }
            for event in projection.events
        ],
        "relationships": [
            {
                "kind": relationship.relationship_type.value,
                "source_key": _entity_key(state.merchant_id, relationship.source),
                "target_key": _entity_key(state.merchant_id, relationship.target),
            }
            for relationship in state.relationships
        ],
    }


def _entity_rows(projection: GraphProjectionInput) -> list[dict[str, Any]]:
    state = projection.state
    rows: dict[str, dict[str, Any]] = {}
    for entity_state in state.entities:
        reference = entity_state.entity
        key = _entity_key(state.merchant_id, reference)
        amount = entity_state.amount
        rows[key] = {
            "key": key,
            "merchant_id": state.merchant_id,
            "entity_type": reference.entity_type.value,
            "provider_id": reference.entity_id,
            "provider_status": entity_state.provider_status,
            "effective_payment_status": (
                None
                if entity_state.effective_payment_status is None
                else entity_state.effective_payment_status.value
            ),
            "amount_subunits": None if amount is None else amount.amount_subunits,
            "currency": None if amount is None else amount.currency,
            "amount_paid_subunits": entity_state.amount_paid_subunits,
            "amount_due_subunits": entity_state.amount_due_subunits,
            "amount_refunded_subunits": entity_state.amount_refunded_subunits,
            "order_id": entity_state.order_id,
            "payment_id": entity_state.payment_id,
            "reference_id": entity_state.reference_id,
            "first_occurred_at": entity_state.first_occurred_at.isoformat(),
            "last_occurred_at": entity_state.last_occurred_at.isoformat(),
            "last_occurred_epoch_ms": _epoch_milliseconds(entity_state.last_occurred_at),
            "latest_event_id": str(entity_state.latest_event_id),
            "event_count": entity_state.event_count,
            "placeholder": False,
        }
    for relationship in state.relationships:
        for reference in (relationship.source, relationship.target):
            key = _entity_key(state.merchant_id, reference)
            rows.setdefault(key, _placeholder_row(state.merchant_id, reference, key))
    return [rows[key] for key in sorted(rows)]


def _placeholder_row(
    merchant_id: str,
    reference: EntityReference,
    key: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "merchant_id": merchant_id,
        "entity_type": reference.entity_type.value,
        "provider_id": reference.entity_id,
        "placeholder": True,
    }


def _entity_key(merchant_id: str, reference: EntityReference) -> str:
    return _key("entity", merchant_id, reference.entity_type.value, reference.entity_id)


def _key(*parts: str) -> str:
    canonical = "\x1f".join(parts).encode()
    return sha256(canonical).hexdigest()


def _epoch_milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1_000)


def _epoch_microseconds(value: datetime) -> int:
    normalized = value.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = normalized - epoch
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
