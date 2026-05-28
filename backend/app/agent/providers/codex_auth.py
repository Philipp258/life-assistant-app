"""OpenAI Codex CLI session auth — load + refresh ChatGPT subscription tokens.

Source of credentials
---------------------
The Codex CLI stores OAuth credentials in ``$CODEX_HOME/auth.json``
(default ``~/.codex/auth.json``). For Life Assistant the user authenticates
on the VPS as the service user, then imports that file into typed provider
settings columns. Runtime refresh writes the new parsed session back via a
persist callback.

JSON shape (``auth.json``)
--------------------------
::

    {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": null,
        "tokens": {
            "id_token": "<JWT>",
            "access_token": "<JWT>",
            "refresh_token": "<string>",
            "account_id": "<string>"
        },
        "last_refresh": "<ISO 8601>"
    }

Refresh flow
------------
When the access_token is within ``TOKEN_REFRESH_MARGIN`` seconds of its
``exp`` claim, POST a form-encoded
``{client_id, grant_type=refresh_token, refresh_token}`` payload to
``https://auth.openai.com/oauth/token`` and write the new tokens back.

API endpoint
------------
The Codex Responses API lives at
``https://chatgpt.com/backend-api/codex/responses`` and requires
``Authorization: Bearer <access_token>`` plus ``chatgpt-account-id``.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx


class AuthInvalidError(Exception):
    """The auth blob is missing required fields or is unparseable."""


class AuthExpiredError(Exception):
    """Codex session token is expired and refresh failed."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Codex CLI session expired and could not be refreshed: {reason}. "
            "SSH to the server and run "
            "`sudo -u life-assistant -H env HOME=/home/life-assistant "
            "codex login --device-auth`, then open Settings and use the server "
            "Codex login again."
        )


CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REFRESH_TOKEN_URL = "https://auth.openai.com/oauth/token"
TOKEN_REFRESH_MARGIN = 60  # seconds before exp to start refreshing


@dataclass
class CodexSession:
    """Parsed Codex CLI session credentials."""

    auth_mode: str | None
    access_token: str
    refresh_token: str
    expires_at: datetime
    account_id: str | None = None
    plan_type: str | None = None
    id_token_raw: str | None = None
    last_refresh: datetime | None = None
    raw: dict[str, Any] | None = None

    @property
    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        return (self.expires_at - now).total_seconds() < TOKEN_REFRESH_MARGIN


PersistCallback = Callable[[CodexSession], Awaitable[None]]
"""Async callback invoked after refresh with the updated parsed session."""


# ── JWT helpers (no signature verification) ───────────────────────


def _decode_jwt_payload(jwt: str) -> dict[str, Any]:
    parts = jwt.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    payload_b64 = parts[1]
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    payload_bytes = base64.urlsafe_b64decode(payload_b64)
    return json.loads(payload_bytes)


def _parse_jwt_expiry(jwt: str) -> datetime:
    claims = _decode_jwt_payload(jwt)
    exp = claims.get("exp")
    if exp is None:
        raise ValueError("JWT has no exp claim")
    return datetime.fromtimestamp(int(exp), tz=timezone.utc)


def _parse_iso_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_id_token_claims(jwt: str) -> tuple[str | None, str | None]:
    """Extract (account_id, plan_type) from the id_token JWT."""
    try:
        claims = _decode_jwt_payload(jwt)
    except (ValueError, json.JSONDecodeError):
        return None, None

    auth_claims = claims.get("https://api.openai.com/auth", {})
    account_id = auth_claims.get("chatgpt_account_id")
    plan_type_raw = auth_claims.get("chatgpt_plan_type")

    plan_type: str | None = None
    if isinstance(plan_type_raw, str):
        plan_type = plan_type_raw
    elif isinstance(plan_type_raw, dict):
        plan_type = plan_type_raw.get("name") or plan_type_raw.get("display_name")

    return account_id, plan_type


# ── Loading ────────────────────────────────────────────────────────


def load_session_from_json(blob: str) -> CodexSession:
    """Parse a Codex auth.json blob into a CodexSession.

    Raises ``AuthInvalidError`` on malformed input. The caller is
    responsible for storing the blob; we don't touch the filesystem.
    """
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise AuthInvalidError(f"auth.json is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise AuthInvalidError("auth.json must be a JSON object")

    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        raise AuthInvalidError("auth.json is missing a 'tokens' object")

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not access_token or not refresh_token:
        raise AuthInvalidError("auth.json tokens must include both access_token and refresh_token")

    try:
        expires_at = _parse_jwt_expiry(access_token)
    except (ValueError, json.JSONDecodeError):
        # Treat as expired so the next refresh kicks in immediately.
        expires_at = datetime.fromtimestamp(0, tz=timezone.utc)

    account_id = tokens.get("account_id")
    plan_type: str | None = None
    id_token_raw = tokens.get("id_token")

    if id_token_raw:
        id_account_id, id_plan_type = _parse_id_token_claims(id_token_raw)
        if not account_id:
            account_id = id_account_id
        plan_type = id_plan_type

    auth_mode = data.get("auth_mode")
    if not isinstance(auth_mode, str):
        auth_mode = None

    return CodexSession(
        auth_mode=auth_mode,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        account_id=account_id,
        plan_type=plan_type,
        id_token_raw=id_token_raw,
        last_refresh=_parse_iso_datetime(data.get("last_refresh")),
        raw=data,
    )


def session_to_json(session: CodexSession) -> str:
    """Serialise a (possibly refreshed) session back to auth.json shape.

    Preserves any extra fields that were present in the original blob,
    so round-trips don't drop ``auth_mode``/``OPENAI_API_KEY`` etc.
    """
    base = dict(session.raw or {})
    tokens = dict(base.get("tokens", {}) if isinstance(base.get("tokens"), dict) else {})
    tokens["access_token"] = session.access_token
    tokens["refresh_token"] = session.refresh_token
    if session.id_token_raw:
        tokens["id_token"] = session.id_token_raw
    if session.account_id:
        tokens["account_id"] = session.account_id
    if session.auth_mode:
        base["auth_mode"] = session.auth_mode
    base["tokens"] = tokens
    base["last_refresh"] = (session.last_refresh or datetime.now(timezone.utc)).isoformat()
    return json.dumps(base, indent=2)


# ── Refresh ────────────────────────────────────────────────────────


async def refresh_session(
    session: CodexSession,
    *,
    force: bool = False,
    persist: PersistCallback | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> CodexSession:
    """Refresh the access token if near expiry, or always when forced.

    If ``persist`` is supplied and a refresh occurred, it is awaited
    with the new auth.json blob so the caller can write it back to its
    store of choice (DB row, file, etc.).
    """
    if not force and not session.is_expired:
        return session

    payload = {
        "client_id": CODEX_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": session.refresh_token,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async def _post(client: httpx.AsyncClient) -> httpx.Response:
        return await client.post(REFRESH_TOKEN_URL, data=payload, headers=headers, timeout=15)

    try:
        if http_client is None:
            async with httpx.AsyncClient() as client:
                resp = await _post(client)
        else:
            resp = await _post(http_client)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise AuthExpiredError(str(exc)) from exc

    token_data = resp.json()

    new_access = token_data.get("access_token") or session.access_token
    new_refresh = token_data.get("refresh_token") or session.refresh_token
    new_id_token = token_data.get("id_token") or session.id_token_raw

    try:
        new_expires = _parse_jwt_expiry(new_access)
    except (ValueError, json.JSONDecodeError):
        new_expires = datetime.fromtimestamp(time.time() + 3600, tz=timezone.utc)

    account_id = session.account_id
    plan_type = session.plan_type
    if new_id_token and new_id_token != session.id_token_raw:
        id_account_id, id_plan_type = _parse_id_token_claims(new_id_token)
        if id_account_id:
            account_id = id_account_id
        if id_plan_type:
            plan_type = id_plan_type

    refreshed = CodexSession(
        auth_mode=session.auth_mode,
        access_token=new_access,
        refresh_token=new_refresh,
        expires_at=new_expires,
        account_id=account_id,
        plan_type=plan_type,
        id_token_raw=new_id_token,
        last_refresh=datetime.now(timezone.utc),
        raw=session.raw,
    )

    if persist is not None:
        await persist(refreshed)

    return refreshed
