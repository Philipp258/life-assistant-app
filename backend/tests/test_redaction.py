"""Tests for app.redaction."""

from __future__ import annotations

from app.redaction import redact_bearer


def test_redact_bearer_in_plain_text() -> None:
    msg = "Authorization: Bearer sk-or-secret-xyz"
    assert redact_bearer(msg) == "Authorization: Bearer ***"


def test_redact_bearer_inside_httpx_bytes_repr() -> None:
    # This is the shape of `str(LocalProtocolError(...))` when an api_key
    # containing newlines is shoved into the Authorization header — the
    # full Codex auth.json blob ends up wrapped in `b'…'`.
    msg = (
        "Illegal header value "
        'b\'Bearer {\\n  "auth_mode": "chatgpt", "tokens": '
        '{"access_token": "eyJ…", "refresh_token": "rt-…"}}\''
    )
    redacted = redact_bearer(msg)
    assert "Bearer ***" in redacted
    assert "auth_mode" not in redacted
    assert "access_token" not in redacted
    assert "refresh_token" not in redacted
    assert "eyJ" not in redacted


def test_redact_bearer_preserves_unrelated_text() -> None:
    msg = "Request to https://example.com failed: 502 Bad Gateway"
    assert redact_bearer(msg) == msg


def test_redact_bearer_stops_at_newline() -> None:
    msg = "Bearer secret-token\nnext log line"
    assert redact_bearer(msg) == "Bearer ***\nnext log line"


def test_redact_bearer_redacts_multiple_occurrences() -> None:
    msg = "first Bearer aaa second Bearer bbb"
    redacted = redact_bearer(msg)
    assert "aaa" not in redacted
    assert "bbb" not in redacted
    assert redacted.count("Bearer ***") == 2
