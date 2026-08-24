"""Opaque cursor and operator read-model input tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from chakravyuh.infrastructure.postgres.operator_read_model import (
    _audit_identity,
    _decode_cursor,
    _encode_cursor,
)


def test_incident_cursor_round_trips_an_aware_time_and_uuid() -> None:
    detected_at = datetime(2026, 8, 24, 18, 30, tzinfo=UTC)
    incident_id = uuid4()

    cursor = _encode_cursor(detected_at, incident_id)

    assert _decode_cursor(cursor) == (detected_at, incident_id)
    assert "{" not in cursor


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "x" * 513,
        "not-json",
        "e30",
        "eyJsYXN0X2RldGVjdGVkX2F0IjoiMjAyNi0wOC0yNFQxODozMDowMCJ9",
    ],
)
def test_incident_cursor_rejects_malformed_or_unbounded_values(cursor: str) -> None:
    with pytest.raises(ValueError, match="invalid incident cursor"):
        _decode_cursor(cursor)


def test_operator_audit_identity_is_trimmed_and_bounded() -> None:
    assert _audit_identity(" operator ", " request ") == ("operator", "request")
    with pytest.raises(ValueError, match="principal"):
        _audit_identity(" ", "request")
    with pytest.raises(ValueError, match="request"):
        _audit_identity("operator", " ")
