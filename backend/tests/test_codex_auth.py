"""Tests for app.agent.providers.codex_auth — JWT parsing, blob load/refresh."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.agent.providers.codex_auth import (
    AuthExpiredError,
    AuthInvalidError,
    CodexSession,
    _decode_jwt_payload,
    _parse_id_token_claims,
    _parse_jwt_expiry,
    load_session_from_json,
    refresh_session,
    session_to_json,
)


def _make_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
    return f"{header}.{body}.{sig}"


def _access_token(*, exp: int | None = None) -> str:
    if exp is None:
        exp = int(time.time()) + 3600
    return _make_jwt({"exp": exp, "sub": "user-123"})


def _id_token(*, account_id: str = "acct-abc", plan_type: str = "pro") -> str:
    return _make_jwt(
        {
            "email": "user@example.com",
            "https://api.openai.com/auth": {
                "chatgpt_account_id": account_id,
                "chatgpt_plan_type": plan_type,
            },
        }
    )


def _auth_blob(*, expired: bool = False) -> str:
    exp = int(time.time()) - 100 if expired else int(time.time()) + 3600
    return json.dumps(
        {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": _id_token(),
                "access_token": _access_token(exp=exp),
                "refresh_token": "refresh-tok-xyz",
                "account_id": "acct-abc",
            },
            "last_refresh": "2026-04-20T10:00:00Z",
        }
    )


# ── JWT parsing ──────────────────────────────────────────────────


def test_decode_jwt_payload_round_trip() -> None:
    decoded = _decode_jwt_payload(_make_jwt({"sub": "u", "exp": 12345}))
    assert decoded["sub"] == "u"
    assert decoded["exp"] == 12345


def test_decode_jwt_payload_invalid_format() -> None:
    with pytest.raises(ValueError, match="Invalid JWT format"):
        _decode_jwt_payload("onlyone")
    with pytest.raises(ValueError, match="Invalid JWT format"):
        _decode_jwt_payload("a.b.c.d")


def test_parse_jwt_expiry_returns_utc() -> None:
    exp = int(time.time()) + 7200
    assert _parse_jwt_expiry(_access_token(exp=exp)) == datetime.fromtimestamp(exp, tz=timezone.utc)


def test_parse_jwt_expiry_missing_claim() -> None:
    with pytest.raises(ValueError, match="no exp claim"):
        _parse_jwt_expiry(_make_jwt({"sub": "u"}))


def test_parse_id_token_claims_basic() -> None:
    account_id, plan_type = _parse_id_token_claims(_id_token(account_id="x", plan_type="plus"))
    assert account_id == "x"
    assert plan_type == "plus"


def test_parse_id_token_claims_dict_plan_type() -> None:
    jwt = _make_jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct-1",
                "chatgpt_plan_type": {"name": "business", "display_name": "Business"},
            },
        }
    )
    account_id, plan_type = _parse_id_token_claims(jwt)
    assert account_id == "acct-1"
    assert plan_type == "business"


def test_parse_id_token_claims_unparseable() -> None:
    assert _parse_id_token_claims("not-a-jwt") == (None, None)


# ── load_session_from_json ───────────────────────────────────────


def test_load_session_happy_path() -> None:
    session = load_session_from_json(_auth_blob())
    assert session.refresh_token == "refresh-tok-xyz"
    assert session.account_id == "acct-abc"
    assert session.plan_type == "pro"
    assert not session.is_expired


def test_load_session_expired_token() -> None:
    session = load_session_from_json(_auth_blob(expired=True))
    assert session.is_expired


def test_load_session_invalid_json() -> None:
    with pytest.raises(AuthInvalidError, match="not valid JSON"):
        load_session_from_json("not json at all")


def test_load_session_missing_tokens() -> None:
    blob = json.dumps({"auth_mode": "chatgpt"})
    with pytest.raises(AuthInvalidError, match="missing a 'tokens' object"):
        load_session_from_json(blob)


def test_load_session_missing_required_fields() -> None:
    blob = json.dumps({"tokens": {"id_token": None, "access_token": None, "refresh_token": None}})
    with pytest.raises(AuthInvalidError, match="must include both"):
        load_session_from_json(blob)


def test_load_session_unparseable_access_token_treated_as_expired() -> None:
    blob = json.dumps({"tokens": {"access_token": "not-a-jwt", "refresh_token": "ref"}})
    session = load_session_from_json(blob)
    assert session.is_expired
    assert session.expires_at == datetime.fromtimestamp(0, tz=timezone.utc)


# ── session_to_json round-trip ───────────────────────────────────


def test_session_to_json_round_trip_preserves_extras() -> None:
    blob = _auth_blob()
    session = load_session_from_json(blob)
    serialised = session_to_json(session)
    data = json.loads(serialised)
    assert data["auth_mode"] == "chatgpt"  # extras preserved
    assert data["tokens"]["refresh_token"] == "refresh-tok-xyz"
    assert "last_refresh" in data


# ── is_expired margin ────────────────────────────────────────────


def test_is_expired_within_margin() -> None:
    session = CodexSession(
        auth_mode="chatgpt",
        access_token="t",
        refresh_token="r",
        expires_at=datetime.fromtimestamp(time.time() + 30, tz=timezone.utc),
    )
    assert session.is_expired


def test_is_expired_outside_margin() -> None:
    session = CodexSession(
        auth_mode="chatgpt",
        access_token="t",
        refresh_token="r",
        expires_at=datetime.fromtimestamp(time.time() + 600, tz=timezone.utc),
    )
    assert not session.is_expired


# ── refresh_session ──────────────────────────────────────────────


def test_refresh_session_noop_when_fresh() -> None:
    session = load_session_from_json(_auth_blob())

    async def go() -> CodexSession:
        return await refresh_session(session)

    assert asyncio.run(go()) is session


def test_refresh_session_calls_persist_with_new_blob() -> None:
    session = load_session_from_json(_auth_blob(expired=True))
    new_access = _access_token(exp=int(time.time()) + 7200)

    persisted: list[CodexSession] = []

    async def persist(refreshed: CodexSession) -> None:
        persisted.append(refreshed)

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: {
        "access_token": new_access,
        "refresh_token": "rotated-refresh",
        "id_token": None,
    }

    async def mock_post(*args, **kwargs):
        return mock_resp

    async def go() -> CodexSession:
        with patch("app.agent.providers.codex_auth.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client
            return await refresh_session(session, persist=persist)

    refreshed = asyncio.run(go())
    assert refreshed.access_token == new_access
    assert refreshed.refresh_token == "rotated-refresh"
    assert not refreshed.is_expired
    assert len(persisted) == 1
    assert persisted[0].refresh_token == "rotated-refresh"


def test_refresh_session_http_error_raises_auth_expired() -> None:
    session = load_session_from_json(_auth_blob(expired=True))

    async def mock_post(*args, **kwargs):
        raise httpx.HTTPError("connection reset")

    async def go() -> None:
        with patch("app.agent.providers.codex_auth.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client
            await refresh_session(session)

    with pytest.raises(AuthExpiredError):
        asyncio.run(go())
