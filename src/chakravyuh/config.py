"""Typed application configuration loaded exclusively from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from chakravyuh.domain.webhooks import MAX_STORED_WEBHOOK_BYTES


class Settings(BaseSettings):
    """Runtime settings shared by the API and asynchronous worker."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CHAKRAVYUH_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_host: str = "0.0.0.0"  # noqa: S104 - intentional container bind address
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    postgres_dsn: str = (
        "postgresql+asyncpg://chakravyuh:local-development-only@localhost:5432/chakravyuh"
    )
    postgres_pool_size: int = Field(default=10, ge=1, le=100)
    postgres_max_overflow: int = Field(default=20, ge=0, le=200)
    postgres_pool_timeout_seconds: float = Field(default=5, gt=0, le=60)
    postgres_statement_timeout_ms: int = Field(default=5_000, ge=100, le=60_000)
    postgres_readiness_timeout_seconds: float = Field(default=2, gt=0, le=10)
    worker_batch_size: int = Field(default=50, ge=1, le=500)
    worker_poll_interval_seconds: float = Field(default=1, gt=0, le=60)
    worker_error_backoff_seconds: float = Field(default=5, gt=0, le=300)
    redis_dsn: str = "redis://localhost:6379/0"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("local-development-only")

    razorpay_key_id: str | None = None
    razorpay_key_secret: SecretStr | None = None
    razorpay_merchant_id: str | None = None
    razorpay_account_id: str | None = None
    razorpay_webhook_secret: SecretStr | None = None
    razorpay_previous_webhook_secrets: list[SecretStr] = Field(default_factory=list)
    max_webhook_body_bytes: int = Field(
        default=MAX_STORED_WEBHOOK_BYTES,
        ge=1_024,
        le=MAX_STORED_WEBHOOK_BYTES,
    )

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_cors(cls, value: list[str]) -> list[str]:
        """Wildcard origins are incompatible with credentialed operator sessions."""
        if "*" in value:
            msg = "CORS wildcard is not permitted"
            raise ValueError(msg)
        return value

    @field_validator(
        "razorpay_key_id",
        "razorpay_merchant_id",
        "razorpay_account_id",
        mode="before",
    )
    @classmethod
    def normalize_blank_optional_text(cls, value: object) -> object | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "razorpay_key_secret",
        "razorpay_webhook_secret",
        mode="before",
    )
    @classmethod
    def normalize_blank_optional_secret(cls, value: object) -> object | None:
        if isinstance(value, str) and not value:
            return None
        return value

    @model_validator(mode="after")
    def validate_webhook_secret_rotation(self) -> "Settings":
        if self.razorpay_webhook_secret is None and self.razorpay_previous_webhook_secrets:
            msg = "previous webhook secrets require a current webhook secret"
            raise ValueError(msg)
        secrets = self.webhook_secrets
        if any(len(secret) < 16 for secret in secrets):
            msg = "webhook secrets must contain at least 16 characters"
            raise ValueError(msg)
        if len(secrets) != len(set(secrets)):
            msg = "webhook rotation secrets must be unique"
            raise ValueError(msg)
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def webhook_secrets(self) -> tuple[str, ...]:
        """Return current and rotation secrets without exposing them in reprs."""
        if self.razorpay_webhook_secret is None:
            return ()
        return (
            self.razorpay_webhook_secret.get_secret_value(),
            *(secret.get_secret_value() for secret in self.razorpay_previous_webhook_secrets),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-by-convention settings object per process."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear cached settings for isolated tests and controlled reloads."""
    get_settings.cache_clear()
