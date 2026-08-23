"""Provider-neutral event contracts."""

from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from chakravyuh.domain.enums import EntityType, EventSource


class EntityReference(BaseModel):
    """Stable reference to a canonical or provider-owned entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_type: EntityType
    entity_id: str = Field(min_length=1, max_length=255)


class NormalizedEvent(BaseModel):
    """Immutable event envelope emitted after provider-specific normalization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    schema_version: int = Field(default=1, ge=1)
    merchant_id: str = Field(min_length=1, max_length=255)
    source: EventSource
    source_event_id: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=255)
    subject: EntityReference
    occurred_at: AwareDatetime
    observed_at: AwareDatetime
    correlation_id: str = Field(min_length=1, max_length=255)
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def observation_cannot_precede_event(self) -> "NormalizedEvent":
        if self.observed_at < self.occurred_at:
            msg = "observed_at cannot precede occurred_at"
            raise ValueError(msg)
        return self
