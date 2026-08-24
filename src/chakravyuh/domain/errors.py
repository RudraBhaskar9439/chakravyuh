"""Domain-level failures that must retain meaning across adapters."""


class EventIdentityConflictError(RuntimeError):
    """A provider event identity was reused with different immutable content."""
