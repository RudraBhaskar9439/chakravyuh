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
