"""Shared test fixtures."""

from collections.abc import Generator

import pytest

from chakravyuh.config import Settings, clear_settings_cache


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        environment="test",
        log_level="CRITICAL",
        cors_origins=["http://testserver"],
    )


@pytest.fixture(autouse=True)
def isolate_settings_cache() -> Generator[None, None, None]:
    clear_settings_cache()
    yield
    clear_settings_cache()
