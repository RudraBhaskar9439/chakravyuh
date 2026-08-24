"""Configuration safety tests."""

import pytest
from pydantic import SecretStr, ValidationError

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


def test_operator_token_hashes_require_bounded_principals_and_unique_sha256() -> None:
    valid_hash = "a" * 64
    assert Settings(operator_token_hashes={"risk-operator": valid_hash}).operator_token_hashes == {
        "risk-operator": valid_hash
    }
    with pytest.raises(ValidationError, match="principal IDs"):
        Settings(operator_token_hashes={" ": valid_hash})
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        Settings(operator_token_hashes={"operator": "not-a-hash"})
    with pytest.raises(ValidationError, match="must be unique"):
        Settings(operator_token_hashes={"first": valid_hash, "second": valid_hash})


def test_outbound_actions_fail_closed_and_accept_test_mode_only() -> None:
    with pytest.raises(ValidationError, match="require a key ID"):
        Settings(
            razorpay_actions_enabled=True,
            razorpay_key_id=None,
            razorpay_key_secret=None,
            razorpay_merchant_id=None,
        )
    with pytest.raises(ValidationError, match="Test Mode credentials only"):
        Settings(
            razorpay_actions_enabled=True,
            razorpay_key_id="rzp_live_forbidden",
            razorpay_key_secret=SecretStr("secret"),
            razorpay_merchant_id="merchant-test",
        )

    configured = Settings(
        razorpay_actions_enabled=True,
        razorpay_key_id="rzp_test_allowed",
        razorpay_key_secret=SecretStr("secret"),
        razorpay_merchant_id="merchant-test",
    )
    assert configured.razorpay_test_actions_configured


def test_test_credentials_do_not_enable_actions_without_explicit_kill_switch() -> None:
    settings = Settings(
        razorpay_key_id="rzp_test_dormant",
        razorpay_key_secret=SecretStr("secret"),
        razorpay_merchant_id="merchant-test",
    )

    assert not settings.razorpay_test_actions_configured
