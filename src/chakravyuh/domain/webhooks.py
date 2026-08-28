"""Immutable contracts for authenticated or authoritatively verified provider intake."""

from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, computed_field

from chakravyuh.domain.enums import EventSource

MAX_STORED_WEBHOOK_BYTES = 262_144


class RawWebhookEvent(BaseModel):
    """A provider event retained exactly as received or canonically API-derived.

    Provider authentication or authoritative API verification happens before this
    contract can be constructed. Webhook bytes remain exact; API fallback bytes are
    canonical, deterministic evidence derived from the allowlisted provider state.
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
