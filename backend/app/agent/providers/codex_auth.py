"""OpenAI Codex CLI session auth — load + refresh ChatGPT subscription tokens.

Source of credentials
---------------------
The Codex CLI stores OAuth credentials in ``$CODEX_HOME/auth.json``
(default ``~/.codex/auth.json``). For Life Assistant the user pastes those file
contents into the provider settings UI; we keep the JSON blob in
``provider_settings.codex_auth_json`` and round-trip it through
``load_session_from_json`` / a persist callback so refresh writes the
new tokens back to the column.

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
``exp`` claim, POST ``{client_id, grant_type=refresh_token, refresh_token}``
to ``https://auth.openai.com/oauth/token`` and write the new tokens back.

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
from typing import Awaitable, Callable

import httpx


class AuthInvalidError(Exception):
    """The auth blob is missing required fields or is unparseable."""


class AuthExpiredError(Exception):
    """Codex session token is expired and refresh failed."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Codex CLI session expired and could not be refreshed: {reason}. "
            "Re-run `codex` locally and paste the new auth.json into Life Assistant."
        )


CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REFRESH_TOKEN_URL = "https://auth.openai.com/oauth/token"
TOKEN_REFRESH_MARGIN = 60  # seconds before exp to start refreshing


PersistCallback = Callable[[str], Awaitable[None]]
"""Async callback invoked after refresh with the updated auth.json blob."""


@dataclass
class CodexSession:
    """Parsed Codex CLI session credentials."""

    access_token: str
    refresh_token: str
    expires_at: datetime
    account_id: str | None = None
    plan_type: str | None = None
    id_token_raw: str | None = None
    raw: dict | None = None

    @property
    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        return (self.expires_at - now).total_seconds() < TOKEN_REFRESH_MARGIN


# ── JWT helpers (no signature verification) ───────────────────────


def _decode_jwt_payload(jwt: str) -> dict:
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

    return CodexSession(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        account_id=account_id,
        plan_type=plan_type,
        id_token_raw=id_token_raw,
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
    base["tokens"] = tokens
    base["last_refresh"] = datetime.now(timezone.utc).isoformat()
    return json.dumps(base, indent=2)


# ── Refresh ────────────────────────────────────────────────────────


async def refresh_session(
    session: CodexSession,
    *,
    persist: PersistCallback | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> CodexSession:
    """Refresh the access token if near expiry; otherwise return as-is.

    If ``persist`` is supplied and a refresh occurred, it is awaited
    with the new auth.json blob so the caller can write it back to its
    store of choice (DB row, file, etc.).
    """
    if not session.is_expired:
        return session

    payload = {
        "client_id": CODEX_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": session.refresh_token,
    }
    headers = {"Content-Type": "application/json"}

    async def _post(client: httpx.AsyncClient) -> httpx.Response:
        return await client.post(REFRESH_TOKEN_URL, json=payload, headers=headers, timeout=15)

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
        access_token=new_access,
        refresh_token=new_refresh,
        expires_at=new_expires,
        account_id=account_id,
        plan_type=plan_type,
        id_token_raw=new_id_token,
        raw=session.raw,
    )

    if persist is not None:
        await persist(session_to_json(refreshed))

    return refreshed
