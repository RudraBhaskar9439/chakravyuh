"""Authenticated recovery-action API boundary tests."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from chakravyuh.api.main import create_app
from chakravyuh.config import Settings
from chakravyuh.domain.actions import (
    ActionProposal,
    ActionView,
    PolicyDecision,
    build_proposal_hash,
)
from chakravyuh.domain.enums import (
    ActionApprovalDecision,
    ActionExecutionStatus,
    ActionRisk,
    ActionType,
    EntityType,
    IncidentType,
    OperatorScope,
    PolicyOutcome,
)
from chakravyuh.domain.errors import ActionControlError, ActionControlErrorCode
from chakravyuh.domain.events import EntityReference
from chakravyuh.domain.money import Money

TOKEN = "action-operator-token-with-enough-entropy"


def _view() -> ActionView:
    now = datetime.now(UTC)
    draft = ActionProposal.model_construct(
        proposal_id=uuid4(),
        incident_id=uuid4(),
        source_revision_id=uuid4(),
        diagnosis_id=uuid4(),
        merchant_id="merchant-test",
        incident_type=IncidentType.AUTHORIZED_NOT_CAPTURED,
        action_type=ActionType.CAPTURE_PAYMENT,
        risk=ActionRisk.MONEY_MOVEMENT,
        target=EntityReference(entity_type=EntityType.PAYMENT, entity_id="pay_123"),
        amount=Money(amount_subunits=10_000, currency="INR"),
        rationale="Capture the exact authorization.",
        evidence_ids=("invariant:authorization-open",),
        confidence=0.97,
        idempotency_key="a" * 64,
        proposal_hash="0" * 64,
        proposed_by="maker",
        request_id="proposal-request",
        proposed_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    proposal = ActionProposal.model_validate(
        {**draft.model_dump(), "proposal_hash": build_proposal_hash(draft)}
    )
    return ActionView(
        proposal=proposal,
        policy=PolicyDecision(
            proposal_id=proposal.proposal_id,
            outcome=PolicyOutcome.REQUIRE_APPROVAL,
            policy_version="test-policy-v1",
            input_hash="b" * 64,
        ),
        execution_status=ActionExecutionStatus.READY,
    )


class _ActionControlPlane:
    def __init__(self) -> None:
        self.view = _view()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.failure: ActionControlError | None = None

    async def propose(self, incident_id: UUID, **parameters: Any) -> ActionView:
        self.calls.append(("propose", {"incident_id": incident_id, **parameters}))
        if self.failure is not None:
            raise self.failure
        return self.view

    async def list_for_incident(
        self, incident_id: UUID, **parameters: Any
    ) -> tuple[ActionView, ...]:
        self.calls.append(("list", {"incident_id": incident_id, **parameters}))
        return (self.view,)

    async def decide(self, proposal_id: UUID, **parameters: Any) -> ActionView:
        self.calls.append(("decide", {"proposal_id": proposal_id, **parameters}))
        if self.failure is not None:
            raise self.failure
        return self.view

    async def execute(self, proposal_id: UUID, **parameters: Any) -> ActionView:
        self.calls.append(("execute", {"proposal_id": proposal_id, **parameters}))
        if self.failure is not None:
            raise self.failure
        return self.view


def _settings() -> Settings:
    return Settings(
        environment="test",
        operator_token_hashes={"maker": hashlib.sha256(TOKEN.encode()).hexdigest()},
    )


def _read_only_settings() -> Settings:
    return Settings(
        environment="test",
        operator_token_hashes={"maker": hashlib.sha256(TOKEN.encode()).hexdigest()},
        operator_principal_scopes={"maker": [OperatorScope.INCIDENT_READ]},
    )


def _client(control: _ActionControlPlane) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=create_app(_settings(), action_control_plane=control)),
        base_url="http://test",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


async def test_proposal_is_server_derived_authenticated_and_not_cacheable() -> None:
    control = _ActionControlPlane()
    incident_id = uuid4()
    async with _client(control) as client:
        response = await client.post(
            f"/v1/operator/incidents/{incident_id}/actions/proposals",
            headers={"X-Request-ID": "proposal-api-request"},
        )

    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["proposal"]["action_type"] == "capture_payment"
    assert control.calls == [
        (
            "propose",
            {
                "incident_id": incident_id,
                "principal_id": "maker",
                "request_id": "proposal-api-request",
            },
        )
    ]


async def test_history_decision_and_execution_forward_exact_operator_identity() -> None:
    control = _ActionControlPlane()
    incident_id = uuid4()
    proposal_id = control.view.proposal.proposal_id
    async with _client(control) as client:
        history = await client.get(f"/v1/operator/incidents/{incident_id}/actions")
        decision = await client.post(
            f"/v1/operator/actions/{proposal_id}/decisions",
            json={"decision": "approved", "rationale": "Evidence and amount verified."},
        )
        execution = await client.post(f"/v1/operator/actions/{proposal_id}/execute")

    assert history.status_code == decision.status_code == execution.status_code == 200
    assert all(
        response.headers["Cache-Control"] == "no-store"
        for response in (history, decision, execution)
    )
    assert control.calls[1][1]["decision"] is ActionApprovalDecision.APPROVED
    assert control.calls[1][1]["rationale"] == "Evidence and amount verified."
    assert all(call[1]["principal_id"] == "maker" for call in control.calls)


async def test_action_body_is_strict_and_unauthenticated_calls_are_rejected() -> None:
    control = _ActionControlPlane()
    proposal_id = control.view.proposal.proposal_id
    async with _client(control) as client:
        invalid = await client.post(
            f"/v1/operator/actions/{proposal_id}/decisions",
            json={"decision": "approved", "rationale": "ok", "amount": 1},
        )
        unauthenticated = await client.post(
            f"/v1/operator/actions/{proposal_id}/execute",
            headers={"Authorization": ""},
        )

    assert invalid.status_code == 422
    assert unauthenticated.status_code == 401
    assert control.calls == []


async def test_control_errors_use_generic_stable_statuses() -> None:
    expected = [
        (ActionControlErrorCode.NOT_FOUND, 404),
        (ActionControlErrorCode.POLICY_DENIED, 403),
        (ActionControlErrorCode.APPROVAL_REQUIRED, 409),
    ]
    for code, status_code in expected:
        control = _ActionControlPlane()
        control.failure = ActionControlError(code)
        async with _client(control) as client:
            response = await client.post(
                f"/v1/operator/actions/{control.view.proposal.proposal_id}/execute"
            )
        assert response.status_code == status_code
        assert response.json() == {"detail": {"code": code.value}}


async def test_action_mutation_scopes_fail_before_control_plane() -> None:
    control = _ActionControlPlane()
    app = create_app(_read_only_settings(), action_control_plane=control)
    incident_id = uuid4()
    proposal_id = control.view.proposal.proposal_id
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        history = await client.get(f"/v1/operator/incidents/{incident_id}/actions")
        proposal = await client.post(f"/v1/operator/incidents/{incident_id}/actions/proposals")
        decision = await client.post(
            f"/v1/operator/actions/{proposal_id}/decisions",
            json={"decision": "approved", "rationale": "Reviewed."},
        )
        execution = await client.post(f"/v1/operator/actions/{proposal_id}/execute")

    assert history.status_code == 200
    assert proposal.status_code == decision.status_code == execution.status_code == 403
    assert [call[0] for call in control.calls] == ["list"]
