"""Stable domain vocabularies shared across adapters."""

from enum import StrEnum


class EntityType(StrEnum):
    MERCHANT = "merchant"
    CUSTOMER = "customer"
    MERCHANT_ORDER = "merchant_order"
    RAZORPAY_ORDER = "razorpay_order"
    PAYMENT = "payment"
    PAYMENT_LINK = "payment_link"
    REFUND = "refund"
    WEBHOOK_EVENT = "webhook_event"
    RECOVERY_CASE = "recovery_case"
    RECOVERY_ACTION = "recovery_action"


class EventSource(StrEnum):
    MERCHANT = "merchant"
    RAZORPAY_API = "razorpay_api"
    RAZORPAY_WEBHOOK = "razorpay_webhook"
    CHAKRAVYUH = "chakravyuh"
    SIMULATOR = "simulator"


class OperatorScope(StrEnum):
    """Explicit least-privilege capabilities for the internal control plane."""

    INCIDENT_READ = "incident:read"
    ACTION_PROPOSE = "action:propose"
    ACTION_APPROVE = "action:approve"
    ACTION_EXECUTE = "action:execute"
    TEST_CHECKOUT = "test-checkout:operate"
    METRICS_READ = "metrics:read"


class NormalizationStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class NormalizationOutcome(StrEnum):
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class JourneyReductionStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class JourneyReductionOutcome(StrEnum):
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class GraphProjectionStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class GraphProjectionOutcome(StrEnum):
    COMPLETED = "completed"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"


class InvariantEvaluationStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class InvariantEvaluationOutcome(StrEnum):
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class IncidentRevisionReason(StrEnum):
    DETECTED = "detected"
    UPDATED = "updated"
    RESOLVED = "resolved"
    REOPENED = "reopened"


class DiagnosisWorkStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class DiagnosisAttemptOutcome(StrEnum):
    COMPLETED = "completed"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"


class DiagnosisDisposition(StrEnum):
    DIAGNOSED = "diagnosed"
    ABSTAINED = "abstained"


class DiagnosisRootCause(StrEnum):
    ASYNCHRONOUS_STATE_LAG = "asynchronous_state_lag"
    MERCHANT_STATE_NOT_UPDATED = "merchant_state_not_updated"
    CAPTURE_NOT_COMPLETED = "capture_not_completed"
    RECOVERY_WORKFLOW_NOT_CLOSED = "recovery_workflow_not_closed"
    DUPLICATE_RECOVERY_WORKFLOW = "duplicate_recovery_workflow"
    PROVIDER_EVENT_REGRESSION = "provider_event_regression"
    UNKNOWN = "unknown"


class DiagnosisAbstentionReason(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    LOW_CONFIDENCE = "low_confidence"
    INVALID_CITATIONS = "invalid_citations"
    UNSUPPORTED_ACTION = "unsupported_action"
    UNSUPPORTED_ROOT_CAUSE = "unsupported_root_cause"
    UNSUPPORTED_INCIDENT = "unsupported_incident"


class EvidenceFactKind(StrEnum):
    INVARIANT = "invariant"
    JOURNEY = "journey"
    ENTITY = "entity"
    EVENT = "event"


class EvidenceRelationshipType(StrEnum):
    SUPPORTS = "supports"
    CONTAINS = "contains"
    HAS_EVENT = "has_event"
    DESCRIBES = "describes"
    PAYMENT_FOR_ORDER = "payment_for_order"
    REFUND_FOR_PAYMENT = "refund_for_payment"
    PAYMENT_LINK_FOR_ORDER = "payment_link_for_order"


class PaymentStatus(StrEnum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    FAILED = "failed"


class JourneyRelationshipType(StrEnum):
    PAYMENT_FOR_ORDER = "payment_for_order"
    REFUND_FOR_PAYMENT = "refund_for_payment"
    PAYMENT_LINK_FOR_ORDER = "payment_link_for_order"


class MerchantOrderStatus(StrEnum):
    CREATED = "created"
    PENDING = "pending"
    PAID = "paid"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class IncidentType(StrEnum):
    CAPTURED_BUT_ORDER_UNPAID = "captured_but_order_unpaid"
    AUTHORIZED_NOT_CAPTURED = "authorized_not_captured"
    FAILED_WITHOUT_RECOVERY = "failed_without_recovery"
    STALE_RECOVERY_AFTER_SUCCESS = "stale_recovery_after_success"
    DUPLICATE_ACTIVE_RECOVERY_LINKS = "duplicate_active_recovery_links"
    EVENT_ORDER_CORRUPTION = "event_order_corruption"


class IncidentStatus(StrEnum):
    DETECTED = "detected"
    INVESTIGATING = "investigating"
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    RESOLVED = "resolved"
    FAILED = "failed"
    ESCALATED = "escalated"


class ActionType(StrEnum):
    FETCH_AUTHORITATIVE_STATE = "fetch_authoritative_state"
    REPLAY_MERCHANT_EVENT = "replay_merchant_event"
    CAPTURE_PAYMENT = "capture_payment"
    CREATE_PAYMENT_LINK = "create_payment_link"
    CANCEL_PAYMENT_LINK = "cancel_payment_link"
    ABSTAIN = "abstain"


class ActionRisk(StrEnum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    MONEY_MOVEMENT = "money_movement"


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ActionApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ActionExecutionStatus(StrEnum):
    READY = "ready"
    PROCESSING = "processing"
    RETRYABLE = "retryable"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    UNCERTAIN = "uncertain"


class ActionExecutionOperation(StrEnum):
    EXECUTE = "execute"
    RECONCILE = "reconcile"


class ActionExecutionOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    BLOCKED = "blocked"
    UNCERTAIN = "uncertain"
