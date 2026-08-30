"""Typed application configuration loaded exclusively from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from chakravyuh.domain.enums import OperatorScope
from chakravyuh.domain.webhooks import MAX_STORED_WEBHOOK_BYTES


class Settings(BaseSettings):
    """Runtime settings shared by the API and asynchronous worker."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CHAKRAVYUH_",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_host: str = "0.0.0.0"  # noqa: S104 - intentional container bind address
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "test", "testserver"]
    )

    postgres_dsn: str = Field(
        default=(
            "postgresql+asyncpg://chakravyuh:local-development-only@localhost:5432/chakravyuh"
        ),
        validation_alias=AliasChoices("CHAKRAVYUH_POSTGRES_DSN", "DATABASE_URL"),
    )
    postgres_pool_size: int = Field(default=10, ge=1, le=100)
    postgres_max_overflow: int = Field(default=20, ge=0, le=200)
    postgres_pool_timeout_seconds: float = Field(default=5, gt=0, le=60)
    postgres_statement_timeout_ms: int = Field(default=5_000, ge=100, le=60_000)
    postgres_readiness_timeout_seconds: float = Field(default=2, gt=0, le=10)
    worker_batch_size: int = Field(default=50, ge=1, le=500)
    journey_reduction_batch_size: int = Field(default=50, ge=1, le=500)
    journey_max_events: int = Field(default=10_000, ge=1, le=100_000)
    invariant_evaluation_batch_size: int = Field(default=50, ge=1, le=500)
    invariant_max_events: int = Field(default=10_000, ge=1, le=100_000)
    invariant_captured_order_grace_seconds: int = Field(default=300, ge=1, le=86_400)
    invariant_authorized_capture_grace_seconds: int = Field(default=900, ge=1, le=86_400)
    invariant_failed_recovery_grace_seconds: int = Field(
        default=1_800,
        ge=1,
        le=604_800,
    )
    invariant_stale_recovery_link_grace_seconds: int = Field(
        default=300,
        ge=1,
        le=86_400,
    )
    worker_poll_interval_seconds: float = Field(default=1, gt=0, le=60)
    worker_error_backoff_seconds: float = Field(default=5, gt=0, le=300)
    redis_dsn: str = "redis://localhost:6379/0"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("local-development-only")
    neo4j_database: str = "neo4j"
    neo4j_connection_timeout_seconds: float = Field(default=5, gt=0, le=60)
    graph_projection_batch_size: int = Field(default=20, ge=1, le=500)
    graph_projection_lease_seconds: int = Field(default=30, ge=1, le=3_600)
    graph_projection_max_failures: int = Field(default=5, ge=1, le=100)
    graph_projection_retry_delay_seconds: float = Field(default=2, ge=0, le=3_600)
    graph_projection_lag_threshold_seconds: float = Field(default=60, gt=0, le=86_400)
    diagnosis_batch_size: int = Field(default=10, ge=1, le=100)
    diagnosis_lease_seconds: int = Field(default=60, ge=1, le=3_600)
    diagnosis_max_failures: int = Field(default=5, ge=1, le=100)
    diagnosis_retry_delay_seconds: float = Field(default=5, ge=0, le=3_600)
    diagnosis_max_facts: int = Field(default=128, ge=1, le=1_000)
    diagnosis_max_relationships: int = Field(default=256, ge=0, le=5_000)
    diagnosis_minimum_confidence: float = Field(default=0.7, ge=0, le=1)
    diagnosis_primary_provider: Literal["gemini", "openrouter"] = "gemini"
    diagnosis_fallback_provider: Literal["gemini", "openrouter"] | None = None
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "CHAKRAVYUH_GEMINI_API_KEY"),
    )
    gemini_model: str = Field(default="gemini-3.5-flash", min_length=1, max_length=128)
    gemini_timeout_seconds: float = Field(default=30, gt=0, le=120)
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = Field(
        default="google/gemini-3.5-flash-lite",
        min_length=3,
        max_length=110,
        pattern=r"^[A-Za-z0-9._~:-]+/[A-Za-z0-9._~:-]+$",
    )
    openrouter_timeout_seconds: float = Field(default=30, gt=0, le=120)
    operator_token_hashes: dict[str, str] = Field(default_factory=dict)
    operator_principal_scopes: dict[str, frozenset[OperatorScope]] = Field(default_factory=dict)
    operator_requests_per_minute: int = Field(default=120, ge=1, le=10_000)
    operator_auth_attempts_per_minute: int = Field(default=30, ge=1, le=1_000)
    rate_limit_backend: Literal["memory", "redis"] = "memory"
    rate_limit_prefix: str = Field(
        default="chakravyuh:rate",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9:_-]+$",
    )

    razorpay_actions_enabled: bool = False
    action_proposal_ttl_seconds: int = Field(default=900, ge=60, le=3_600)
    action_execution_lease_seconds: int = Field(default=30, ge=5, le=300)
    action_recovery_link_ttl_seconds: int = Field(default=86_400, ge=900, le=604_800)
    action_max_capture_subunits: int = Field(default=1_000_000, ge=1, le=100_000_000)
    action_minimum_capture_confidence: float = Field(default=0.9, ge=0, le=1)
    action_max_payment_link_subunits: int = Field(default=100_000, ge=1, le=10_000_000)
    action_minimum_payment_link_confidence: float = Field(default=0.9, ge=0, le=1)
    razorpay_action_timeout_seconds: float = Field(default=10, gt=0, le=30)

    test_checkout_enabled: bool = False
    test_checkout_amount_subunits: int = Field(default=1_000, ge=100, le=100_000)
    test_checkout_ttl_seconds: int = Field(default=1_800, ge=300, le=3_600)

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

    @field_validator("trusted_hosts")
    @classmethod
    def validate_trusted_hosts(cls, value: list[str]) -> list[str]:
        if not value or any(not host.strip() for host in value):
            msg = "trusted hosts must contain at least one non-empty host"
            raise ValueError(msg)
        if any(
            "*" in host
            or len(host) > 253
            or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.:-"
                for character in host
            )
            for host in value
        ):
            msg = "trusted host wildcard or invalid character is not permitted"
            raise ValueError(msg)
        return value

    @field_validator("postgres_dsn", mode="before")
    @classmethod
    def normalize_postgres_driver(cls, value: object) -> object:
        """Use asyncpg when a hosting provider supplies a standard Postgres URL."""
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if isinstance(value, str) and value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value

    @field_validator(
        "razorpay_key_id",
        "razorpay_merchant_id",
        "razorpay_account_id",
        "diagnosis_fallback_provider",
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
        "gemini_api_key",
        "openrouter_api_key",
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
        if self.diagnosis_primary_provider == self.diagnosis_fallback_provider:
            msg = "diagnosis fallback provider must differ from the primary provider"
            raise ValueError(msg)
        for principal_id, token_hash in self.operator_token_hashes.items():
            if not principal_id.strip() or len(principal_id) > 64:
                msg = "operator token principal IDs must contain between 1 and 64 characters"
                raise ValueError(msg)
            if len(token_hash) != 64 or any(
                character not in "0123456789abcdef" for character in token_hash
            ):
                msg = "operator token hashes must be lowercase SHA-256 hex"
                raise ValueError(msg)
        if len(self.operator_token_hashes) != len(set(self.operator_token_hashes.values())):
            msg = "operator token hashes must be unique"
            raise ValueError(msg)
        unknown_scope_principals = set(self.operator_principal_scopes) - set(
            self.operator_token_hashes
        )
        if unknown_scope_principals:
            msg = "operator scopes require a configured token principal"
            raise ValueError(msg)
        if any(not scopes for scopes in self.operator_principal_scopes.values()):
            msg = "configured operator scope sets must not be empty"
            raise ValueError(msg)
        if self.is_production and self.operator_token_hashes:
            if set(self.operator_principal_scopes) != set(self.operator_token_hashes):
                msg = "production operator principals require explicit scopes"
                raise ValueError(msg)
            if self.rate_limit_backend != "redis":
                msg = "production operator authentication requires Redis rate limiting"
                raise ValueError(msg)
        if self.razorpay_actions_enabled:
            if (
                self.razorpay_key_id is None
                or self.razorpay_key_secret is None
                or self.razorpay_merchant_id is None
            ):
                msg = "Razorpay actions require a key ID, key secret, and merchant ID"
                raise ValueError(msg)
            if not self.razorpay_key_id.startswith("rzp_test_"):
                msg = "Razorpay actions accept Test Mode credentials only"
                raise ValueError(msg)
        if self.test_checkout_enabled:
            if self.is_production:
                msg = "Test Checkout cannot be enabled in the production environment"
                raise ValueError(msg)
            if not self.razorpay_test_credentials_configured:
                msg = "Test Checkout requires Test Mode key credentials and a merchant ID"
                raise ValueError(msg)
            if not self.operator_token_hashes:
                msg = "Test Checkout requires at least one scoped operator token"
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

    @property
    def razorpay_test_actions_configured(self) -> bool:
        return bool(
            self.razorpay_actions_enabled
            and self.razorpay_key_id is not None
            and self.razorpay_key_id.startswith("rzp_test_")
            and self.razorpay_key_secret is not None
            and self.razorpay_merchant_id is not None
        )

    @property
    def razorpay_test_credentials_configured(self) -> bool:
        return bool(
            self.razorpay_key_id is not None
            and self.razorpay_key_id.startswith("rzp_test_")
            and self.razorpay_key_secret is not None
            and self.razorpay_merchant_id is not None
        )

    @property
    def razorpay_test_provider_configured(self) -> bool:
        return bool(self.razorpay_test_actions_configured or self.test_checkout_enabled)

    def scopes_for_principal(self, principal_id: str) -> frozenset[OperatorScope]:
        """Return explicit scopes, with a non-production compatibility default for local review."""

        configured = self.operator_principal_scopes.get(principal_id)
        if configured is not None:
            return configured
        if not self.is_production and principal_id in self.operator_token_hashes:
            return frozenset(OperatorScope)
        return frozenset()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-by-convention settings object per process."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear cached settings for isolated tests and controlled reloads."""
    get_settings.cache_clear()
