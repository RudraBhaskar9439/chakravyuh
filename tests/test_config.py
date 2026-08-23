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
