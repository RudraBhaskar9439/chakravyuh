"""Immutable contracts for verified provider webhook intake."""

from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, computed_field

from chakravyuh.domain.enums import EventSource

MAX_STORED_WEBHOOK_BYTES = 262_144


class RawWebhookEvent(BaseModel):
    """A signature-verified webhook retained exactly as it was received.

    Authentication happens before this contract can be constructed. The exact raw
    bytes are retained because parsing and re-encoding JSON would destroy the bytes
    over which the provider signature was calculated.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    merchant_id: str = Field(min_length=1, max_length=255)
    source: EventSource
    source_event_id: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=255)
    account_id: str | None = Field(default=None, min_length=1, max_length=255)
    occurred_at: AwareDatetime
    observed_at: AwareDatetime
    payload: dict[str, JsonValue]
    raw_body: bytes = Field(min_length=1, max_length=MAX_STORED_WEBHOOK_BYTES)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def body_sha256(self) -> str:
        """Return a stable integrity digest without exposing payload content."""
        return sha256(self.raw_body).hexdigest()
