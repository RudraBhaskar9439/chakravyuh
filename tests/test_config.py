"""Configuration safety tests."""

import pytest
from pydantic import ValidationError

from chakravyuh.config import Settings, get_settings


def test_settings_load_prefixed_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CHAKRAVYUH_ENVIRONMENT", "staging")
    monkeypatch.setenv("CHAKRAVYUH_API_PORT", "9000")

    settings = get_settings()

    assert settings.environment == "staging"
    assert settings.api_port == 9000
    assert not settings.is_production


def test_settings_identify_production() -> None:
    assert Settings(environment="production").is_production


def test_wildcard_cors_is_rejected() -> None:
    with pytest.raises(ValidationError, match="CORS wildcard is not permitted"):
        Settings(cors_origins=["*"])


def test_blank_optional_provider_configuration_is_disabled() -> None:
    settings = Settings(
        razorpay_merchant_id=" ",
        razorpay_account_id="",
        razorpay_webhook_secret="",
    )

    assert settings.razorpay_merchant_id is None
    assert settings.razorpay_account_id is None
    assert settings.webhook_secrets == ()


def test_webhook_secret_rotation_is_validated() -> None:
    settings = Settings(
        razorpay_webhook_secret="current-secret-123",
        razorpay_previous_webhook_secrets=["previous-secret-1"],
    )
    assert settings.webhook_secrets == ("current-secret-123", "previous-secret-1")

    with pytest.raises(ValidationError, match="at least 16"):
        Settings(razorpay_webhook_secret="too-short")
    with pytest.raises(ValidationError, match="must be unique"):
        Settings(
            razorpay_webhook_secret="duplicate-secret",
            razorpay_previous_webhook_secrets=["duplicate-secret"],
        )
    with pytest.raises(ValidationError, match="require a current"):
        Settings(razorpay_previous_webhook_secrets=["previous-secret-1"])
