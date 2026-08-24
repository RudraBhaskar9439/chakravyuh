"""Domain-level failures that must retain meaning across adapters."""

from enum import StrEnum


class EventIdentityConflictError(RuntimeError):
    """A provider event identity was reused with different immutable content."""


class NormalizationErrorCode(StrEnum):
    """Stable, payload-free reasons why a verified event cannot be normalized."""

    UNSUPPORTED_SOURCE = "unsupported_source"
    UNSUPPORTED_EVENT_TYPE = "unsupported_event_type"
    MISSING_PRIMARY_ENTITY = "missing_primary_entity"
    MISSING_ENTITY_ID = "missing_entity_id"
    EVENT_TIME_AFTER_OBSERVATION = "event_time_after_observation"


class NormalizationError(ValueError):
    """A permanent failure caused by the shape or semantics of one raw event."""

    def __init__(self, code: NormalizationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class ReplayNotAllowedError(RuntimeError):
    """A normalization item was not in a state that permits audited replay."""


class JourneyReductionErrorCode(StrEnum):
    """Stable reasons why one correlation cannot currently be reduced."""

    JOURNEY_TOO_LARGE = "journey_too_large"


class JourneyReductionError(ValueError):
    """A bounded permanent failure while reducing one correlation."""

    def __init__(self, code: JourneyReductionErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class JourneyReductionReplayNotAllowedError(RuntimeError):
    """A journey reduction was not dead-lettered and cannot be replayed."""


class ProjectionLeaseLostError(RuntimeError):
    """A projection worker no longer owns the lease it tried to complete."""


class StaleGraphProjectionError(RuntimeError):
    """Neo4j already contains a newer generation than the requested projection."""


class GraphRebuildNotAllowedError(RuntimeError):
    """A requested graph rebuild had no authoritative states to enqueue."""


class InvariantEvaluationErrorCode(StrEnum):
    """Stable reasons a journey cannot currently be evaluated."""

    JOURNEY_TOO_LARGE = "invariant_journey_too_large"


class InvariantEvaluationError(ValueError):
    """A bounded permanent invariant-evaluation failure."""

    def __init__(self, code: InvariantEvaluationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class DiagnosisErrorCode(StrEnum):
    INTERNAL = "diagnosis_internal_error"
    GRAPH_UNAVAILABLE = "diagnosis_graph_unavailable"
    GRAPH_STALE = "diagnosis_graph_stale"
    EVIDENCE_TOO_LARGE = "diagnosis_evidence_too_large"
    EVIDENCE_INCOMPLETE = "diagnosis_evidence_incomplete"
    MODEL_UNAVAILABLE = "diagnosis_model_unavailable"
    MODEL_TIMEOUT = "diagnosis_model_timeout"
    MODEL_INCOMPLETE = "diagnosis_model_incomplete"
    MODEL_INVALID_RESPONSE = "diagnosis_model_invalid_response"


class DiagnosisProcessingError(Exception):
    """Stable diagnosis failure safe for retry/dead-letter audit."""

    def __init__(self, code: DiagnosisErrorCode, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code.value)


class DiagnosisLeaseLostError(RuntimeError):
    """Raised when a diagnosis worker no longer owns its checkpoint lease."""


class ActionControlErrorCode(StrEnum):
    NOT_FOUND = "action_resource_not_found"
    DIAGNOSIS_REQUIRED = "action_diagnosis_required"
    DIAGNOSIS_ABSTAINED = "action_diagnosis_abstained"
    STALE = "action_proposal_stale"
    EXPIRED = "action_proposal_expired"
    POLICY_DENIED = "action_policy_denied"
    APPROVAL_REQUIRED = "action_approval_required"
    MAKER_CHECKER_VIOLATION = "action_maker_checker_violation"
    REJECTED = "action_rejected"
    EXECUTION_IN_PROGRESS = "action_execution_in_progress"
    EXECUTION_TERMINAL = "action_execution_terminal"
    LEASE_LOST = "action_execution_lease_lost"
    PROVIDER_UNAVAILABLE = "action_provider_unavailable"
    PROVIDER_INVALID_RESPONSE = "action_provider_invalid_response"
    PROVIDER_REJECTED = "action_provider_rejected"
    AUTHORITATIVE_STATE_CHANGED = "action_authoritative_state_changed"


class ActionControlError(RuntimeError):
    """Stable, secret-free failure returned by the action control plane."""

    def __init__(self, code: ActionControlErrorCode, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code.value)


class RazorpayActionError(RuntimeError):
    """Sanitized provider failure with no response payload or credential material."""

    def __init__(self, code: ActionControlErrorCode, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code.value)
