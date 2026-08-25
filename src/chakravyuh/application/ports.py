"""Interfaces implemented by infrastructure adapters in later phases."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from chakravyuh.domain.actions import ActionProposal, PolicyDecision
from chakravyuh.domain.events import NormalizedEvent
from chakravyuh.domain.incidents import Incident
from chakravyuh.domain.webhooks import RawWebhookEvent

if TYPE_CHECKING:
    from chakravyuh.application.invariant_evaluation import InvariantEvaluationBatchResult
    from chakravyuh.application.journey_reduction import JourneyReductionBatchResult
    from chakravyuh.application.normalization import NormalizationBatchResult
    from chakravyuh.domain.actions import (
        ActionExecutionClaim,
        ActionExecutionResult,
        ActionProposalSeed,
        ActionView,
        ProviderPaymentState,
    )
    from chakravyuh.domain.diagnoses import DiagnosisReceipt, DiagnosisWorkClaim
    from chakravyuh.domain.enums import ActionApprovalDecision
    from chakravyuh.domain.evidence import DiagnosisSeed, EvidenceSubgraph, GraphEvidenceSnapshot
    from chakravyuh.domain.invariants import InvariantEvaluationResult
    from chakravyuh.domain.journeys import PaymentJourneyState
    from chakravyuh.domain.money import Money
    from chakravyuh.domain.operators import IncidentDetail, IncidentOverview, IncidentPage
    from chakravyuh.domain.projections import (
        GraphProjectionInput,
        GraphProjectionReceipt,
        GraphRebuildCandidate,
        GraphRebuildReceipt,
        ProjectionLag,
        ProjectionWorkClaim,
    )
    from chakravyuh.domain.test_checkout import (
        PreparedTestCheckout,
        ProviderManualCaptureOrder,
        TestCheckoutOrder,
        TestCheckoutVerification,
    )


class Clock(Protocol):
    def now(self) -> datetime: ...


class EventStore(Protocol):
    async def append(self, event: NormalizedEvent) -> bool:
        """Persist once and return False when the source event was already stored."""
        ...

    async def read_for_merchant(self, merchant_id: str) -> Sequence[NormalizedEvent]: ...


class WebhookEventStore(Protocol):
    async def append(self, event: RawWebhookEvent) -> bool:
        """Persist once and return False for an identical provider retry."""
        ...

    async def get(
        self,
        merchant_id: str,
        source_event_id: str,
    ) -> RawWebhookEvent | None: ...


class WebhookNormalizer(Protocol):
    """Convert one verified provider event into the stable domain envelope."""

    version: str

    def normalize(self, event: RawWebhookEvent) -> NormalizedEvent: ...


class NormalizationWorkRepository(Protocol):
    """Atomically claim raw events and commit their normalization outcome."""

    async def process_batch(
        self,
        *,
        normalizer: WebhookNormalizer,
        worker_id: str,
        batch_size: int,
    ) -> NormalizationBatchResult: ...

    async def request_replay(
        self,
        event_id: UUID,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID: ...


class JourneyReducer(Protocol):
    """Pure, versioned reduction of one complete merchant correlation."""

    version: str

    def reduce(self, events: list[NormalizedEvent]) -> PaymentJourneyState: ...


class JourneyReductionRepository(Protocol):
    """Durably claim and materialize temporal payment journeys."""

    async def process_batch(
        self,
        *,
        reducer: JourneyReducer,
        worker_id: str,
        batch_size: int,
        max_events_per_journey: int,
    ) -> JourneyReductionBatchResult: ...

    async def request_replay(
        self,
        merchant_id: str,
        correlation_id: str,
        *,
        requested_by: str,
        reason: str,
    ) -> UUID: ...

    async def get(
        self,
        merchant_id: str,
        correlation_id: str,
    ) -> PaymentJourneyState | None: ...


class InvariantEvaluator(Protocol):
    version: str

    def evaluate(
        self,
        state: PaymentJourneyState,
        events: tuple[NormalizedEvent, ...],
        *,
        as_of: datetime,
    ) -> InvariantEvaluationResult: ...


class InvariantEvaluationRepository(Protocol):
    async def process_batch(
        self,
        *,
        evaluator: InvariantEvaluator,
        worker_id: str,
        batch_size: int,
        max_events_per_journey: int,
    ) -> InvariantEvaluationBatchResult: ...


class GraphEvidenceReader(Protocol):
    async def snapshot(
        self,
        seed: DiagnosisSeed,
        *,
        max_facts: int,
        max_relationships: int,
    ) -> GraphEvidenceSnapshot: ...

    async def close(self) -> None: ...


class EvidenceAssembler(Protocol):
    async def assemble(self, seed: DiagnosisSeed) -> EvidenceSubgraph: ...


class StructuredDiagnostician(Protocol):
    async def diagnose(self, evidence: EvidenceSubgraph) -> DiagnosisReceipt: ...

    async def close(self) -> None: ...


class DiagnosisRepository(Protocol):
    async def claim_batch(
        self,
        *,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
    ) -> Sequence[DiagnosisWorkClaim]: ...

    async def load(self, claim: DiagnosisWorkClaim) -> DiagnosisSeed: ...

    async def complete(self, claim: DiagnosisWorkClaim, receipt: DiagnosisReceipt) -> None: ...

    async def fail(
        self,
        claim: DiagnosisWorkClaim,
        *,
        error_code: str,
        retryable: bool,
        max_failures: int,
        retry_delay_seconds: float,
    ) -> bool: ...


class OperatorReadModel(Protocol):
    async def overview(self, *, principal_id: str, request_id: str) -> IncidentOverview: ...

    async def list_incidents(
        self,
        *,
        principal_id: str,
        request_id: str,
        statuses: Sequence[str],
        limit: int,
        cursor: str | None,
    ) -> IncidentPage: ...

    async def get_incident(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> IncidentDetail | None: ...


class DatabaseLifecycle(Protocol):
    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class IncidentRepository(Protocol):
    async def save(self, incident: Incident) -> None: ...

    async def get(self, incident_id: UUID) -> Incident | None: ...


class PolicyEngine(Protocol):
    def evaluate(self, proposal: ActionProposal) -> PolicyDecision: ...


class RecoveryActionRepository(Protocol):
    async def load_seed(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> ActionProposalSeed | None: ...

    async def create_proposal(
        self,
        proposal: ActionProposal,
        policy: PolicyDecision,
        *,
        principal_id: str,
        request_id: str,
    ) -> ActionView: ...

    async def list_for_incident(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> Sequence[ActionView]: ...

    async def decide(
        self,
        proposal_id: UUID,
        *,
        principal_id: str,
        request_id: str,
        decision: ActionApprovalDecision,
        rationale: str,
    ) -> ActionView: ...

    async def claim_execution(
        self,
        proposal_id: UUID,
        *,
        principal_id: str,
        request_id: str,
        lease_seconds: int,
    ) -> ActionExecutionClaim | ActionView: ...

    async def mark_mutation_started(self, claim: ActionExecutionClaim) -> None: ...

    async def complete_execution(
        self,
        claim: ActionExecutionClaim,
        result: ActionExecutionResult,
    ) -> ActionView: ...


class RazorpayPaymentGateway(Protocol):
    async def fetch_payment(self, payment_id: str) -> ProviderPaymentState: ...

    async def capture_payment(
        self,
        payment_id: str,
        amount: Money,
    ) -> ProviderPaymentState: ...

    async def close(self) -> None: ...


class RazorpayTestCheckoutGateway(Protocol):
    async def create_manual_capture_order(
        self,
        *,
        amount: Money,
        receipt: str,
    ) -> ProviderManualCaptureOrder: ...

    def verify_checkout_signature(
        self,
        *,
        order_id: str,
        payment_id: str,
        signature: str,
    ) -> bool: ...

    async def fetch_payment(self, payment_id: str) -> ProviderPaymentState: ...


class TestCheckoutRepository(Protocol):
    async def record_order(self, order: TestCheckoutOrder) -> TestCheckoutOrder: ...

    async def get_order(self, order_id: str) -> TestCheckoutOrder | None: ...

    async def record_verification(
        self,
        verification: TestCheckoutVerification,
    ) -> TestCheckoutVerification: ...


class TestCheckoutControlPlane(Protocol):
    async def prepare(
        self,
        *,
        principal_id: str,
        request_id: str,
    ) -> PreparedTestCheckout: ...

    async def verify(
        self,
        *,
        order_id: str,
        payment_id: str,
        signature: str,
        principal_id: str,
        request_id: str,
    ) -> TestCheckoutVerification: ...


class ActionControlPlane(Protocol):
    async def propose(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> ActionView: ...

    async def list_for_incident(
        self,
        incident_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> Sequence[ActionView]: ...

    async def decide(
        self,
        proposal_id: UUID,
        *,
        principal_id: str,
        request_id: str,
        decision: ActionApprovalDecision,
        rationale: str,
    ) -> ActionView: ...

    async def execute(
        self,
        proposal_id: UUID,
        *,
        principal_id: str,
        request_id: str,
    ) -> ActionView: ...


class GraphProjector(Protocol):
    async def initialize_schema(self) -> None: ...

    async def verify_connectivity(self) -> None: ...

    async def project(self, projection: GraphProjectionInput) -> GraphProjectionReceipt: ...

    async def prune_before(self, rebuild: GraphRebuildCandidate) -> GraphRebuildReceipt: ...

    async def close(self) -> None: ...


class GraphProjectionRepository(Protocol):
    async def claim_batch(
        self,
        *,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
    ) -> Sequence[ProjectionWorkClaim]: ...

    async def load(self, claim: ProjectionWorkClaim) -> GraphProjectionInput: ...

    async def complete(
        self,
        claim: ProjectionWorkClaim,
        receipt: GraphProjectionReceipt,
    ) -> None: ...

    async def fail(
        self,
        claim: ProjectionWorkClaim,
        *,
        error_code: str,
        max_failures: int,
        retry_delay_seconds: float,
    ) -> bool: ...

    async def lag(self) -> ProjectionLag: ...

    async def request_rebuild(
        self,
        *,
        requested_by: str,
        reason: str,
    ) -> tuple[UUID, int]: ...

    async def finalizable_rebuilds(self, *, limit: int) -> Sequence[GraphRebuildCandidate]: ...

    async def complete_rebuild(
        self,
        rebuild: GraphRebuildCandidate,
        receipt: GraphRebuildReceipt,
    ) -> bool: ...


class AuthoritativeStateReader(Protocol):
    async def fetch(self, provider_entity_id: str) -> NormalizedEvent: ...
