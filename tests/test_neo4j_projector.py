"""Pure and driver-boundary tests for the Neo4j projector."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from chakravyuh.config import Settings
from chakravyuh.domain.errors import StaleGraphProjectionError
from chakravyuh.domain.journeys import journey_state_hash, reduce_payment_journey
from chakravyuh.domain.projections import GraphProjectionInput, GraphRebuildCandidate
from chakravyuh.infrastructure.neo4j.projector import (
    Neo4jPaymentGraphProjector,
    _parameters,
    _replace_journey,
)
from chakravyuh.simulation.journeys import JourneyScenario, generate_synthetic_journey


class FakeResult:
    def __init__(self, record: dict[str, object] | None = None) -> None:
        self.record = record
        self.consumed = False

    async def single(self):  # type: ignore[no-untyped-def]
        return self.record

    async def consume(self) -> None:
        self.consumed = True


class FakeTransaction:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def run(self, statement: str, **parameters):  # type: ignore[no-untyped-def]
        self.statements.append(statement)
        if "AS should_apply" in statement:
            return FakeResult({"should_apply": True})
        if "RETURN [node IN collect(old)" in statement:
            return FakeResult({"old_keys": ["orphan-key"]})
        if "RETURN count(node) AS removed" in statement:
            return FakeResult({"removed": 2})
        return FakeResult()


class FakeSession:
    def __init__(self) -> None:
        self.transaction = FakeTransaction()
        self.schema_statements: list[str] = []

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
        return None

    async def run(self, statement: str) -> FakeResult:
        self.schema_statements.append(statement)
        return FakeResult()

    async def execute_write(self, function, parameters):  # type: ignore[no-untyped-def]
        return await function(self.transaction, parameters)


class FakeDriver:
    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []
        self.verified = False
        self.closed = False

    def session(self, **kwargs) -> FakeSession:  # type: ignore[no-untyped-def]
        session = FakeSession()
        self.sessions.append(session)
        return session

    async def verify_connectivity(self) -> None:
        self.verified = True

    async def close(self) -> None:
        self.closed = True


def _projection() -> GraphProjectionInput:
    journey = generate_synthetic_journey(JourneyScenario.PARTIALLY_REFUNDED, seed=51)
    state = reduce_payment_journey(list(journey.events))
    return GraphProjectionInput(
        state_generation=5,
        projection_epoch=journey.events[0].observed_at,
        state_hash=journey_state_hash(state),
        state=state,
        events=journey.events,
    )


def test_parameters_are_stable_flat_and_payload_free() -> None:
    projection = _projection()
    first = _parameters(projection, projected_at=projection.state.last_occurred_at)
    second = _parameters(projection, projected_at=projection.state.last_occurred_at)

    assert first == second
    assert len(first["entities"]) == 3
    assert len(first["events"]) == 5
    assert first["relationships"]
    assert all("payload" not in event for event in first["events"])
    assert all(
        isinstance(value, (str, int, bool, type(None))) for value in first["journey"].values()
    )


@pytest.mark.parametrize(
    "change",
    [
        {"state_hash": "0" * 64},
        {"events": ()},
    ],
)
def test_projection_input_rejects_inconsistent_authoritative_evidence(
    change: dict[str, object],
) -> None:
    values = _projection().model_dump()
    values.update(change)

    with pytest.raises(ValidationError, match="projection"):
        GraphProjectionInput.model_validate(values)


def test_projection_input_rejects_duplicate_or_foreign_evidence() -> None:
    projection = _projection()
    duplicated = projection.model_dump()
    duplicated["events"] = list(duplicated["events"])
    duplicated["events"][1] = duplicated["events"][0]
    foreign = projection.model_dump()
    foreign["events"] = list(foreign["events"])
    foreign["events"][0]["merchant_id"] = "another-merchant"

    with pytest.raises(ValidationError, match="duplicate"):
        GraphProjectionInput.model_validate(duplicated)
    with pytest.raises(ValidationError, match="different journey"):
        GraphProjectionInput.model_validate(foreign)


async def test_projector_initializes_schema_projects_atomically_and_closes() -> None:
    driver = FakeDriver()
    projector = Neo4jPaymentGraphProjector(
        Settings(environment="test"),
        driver=driver,  # type: ignore[arg-type]
    )
    projection = _projection()

    await projector.initialize_schema()
    await projector.verify_connectivity()
    receipt = await projector.project(projection)
    await projector.close()

    assert len(driver.sessions[0].schema_statements) == 4
    statements = driver.sessions[1].transaction.statements
    assert any("MERGE (merchant:Merchant" in statement for statement in statements)
    assert any("DETACH DELETE node" in statement for statement in statements)
    assert receipt.state_hash == projection.state_hash
    assert receipt.entity_count == 3
    assert receipt.event_count == 5
    assert driver.verified is True
    assert driver.closed is True


async def test_projector_prunes_only_nodes_older_than_a_rebuild_epoch() -> None:
    driver = FakeDriver()
    projector = Neo4jPaymentGraphProjector(
        Settings(environment="test"),
        driver=driver,  # type: ignore[arg-type]
    )
    rebuild = GraphRebuildCandidate(
        rebuild_id=uuid4(),
        projection_epoch=_projection().projection_epoch,
    )

    receipt = await projector.prune_before(rebuild)

    assert receipt.journey_count_removed == 2
    assert receipt.entity_count_removed == 2
    assert receipt.event_count_removed == 2
    assert receipt.merchant_count_removed == 2
    statements = driver.sessions[0].transaction.statements
    assert "projection_epoch_us" in statements[0]


async def test_neo4j_generation_guard_ignores_expired_stale_writer() -> None:
    class StaleTransaction(FakeTransaction):
        async def run(self, statement: str, **parameters):  # type: ignore[no-untyped-def]
            self.statements.append(statement)
            return FakeResult({"should_apply": False})

    transaction = StaleTransaction()
    assert not await _replace_journey(
        transaction,
        {
            "journey_key": "key",
            "state_generation": 1,
            "projection_epoch_us": 1,
        },
    )

    assert len(transaction.statements) == 1


async def test_projector_reports_a_rejected_stale_generation() -> None:
    class StaleSession(FakeSession):
        async def execute_write(self, function, parameters):  # type: ignore[no-untyped-def]
            return False

    class StaleDriver(FakeDriver):
        def session(self, **kwargs) -> StaleSession:  # type: ignore[no-untyped-def]
            session = StaleSession()
            self.sessions.append(session)
            return session

    projector = Neo4jPaymentGraphProjector(
        Settings(environment="test"),
        driver=StaleDriver(),  # type: ignore[arg-type]
    )

    with pytest.raises(StaleGraphProjectionError, match="stale"):
        await projector.project(_projection())
