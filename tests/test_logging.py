"""Logging configuration tests."""

import logging

import structlog

from chakravyuh.logging import configure_logging


def test_configure_console_logging() -> None:
    configure_logging("INFO", json_logs=False)
    assert logging.getLogger().level == logging.INFO
    assert structlog.is_configured()


def test_configure_json_logging() -> None:
    configure_logging("WARNING", json_logs=True)
    assert logging.getLogger().level == logging.WARNING
