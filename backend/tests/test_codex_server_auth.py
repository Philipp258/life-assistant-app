from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.agent.providers.codex_auth import AuthExpiredError, CodexSession
from app.provider_settings import codex_server_auth
from app.provider_settings.models import ProviderSettings


def _make_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(b"sig").rstrip(b"=")
    return b".".join([header, body, sig]).decode()


def _access_token(*, expired: bool = False) -> str:
    exp = int(time.time()) - 120 if expired else int(time.time()) + 3600
    return _make_jwt({"exp": exp, "sub": "user"})


def _id_token() -> str:
    return _make_jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct-file",
                "chatgpt_plan_type": "plus",
            }
        }
    )


def _auth_blob(*, expired: bool = False) -> str:
    return json.dumps(
        {
            "auth_mode": "chatgpt",
            "tokens": {
                "access_token": _access_token(expired=expired),
                "refresh_token": "refresh-file-secret",
                "id_token": _id_token(),
            },
            "last_refresh": "2026-05-25T10:00:00Z",
        }
    )


@pytest.fixture
def server_auth_env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(codex_server_auth, "codex_cli_installed", lambda: True)
    return tmp_path / "auth.json"


def _row(db_session: Session) -> ProviderSettings:
    row = db_session.get(ProviderSettings, 1)
    assert row is not None
    return row


def test_server_auth_status_missing_cli(
    db_session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(codex_server_auth, "codex_cli_installed", lambda: False)

    status = asyncio.run(codex_server_auth.server_auth_status(_row(db_session)))

    assert status.codex_cli_installed is False
    assert status.importable is False
    assert "Codex CLI is not installed" in (status.error or "")


def test_server_auth_status_missing_file(db_session: Session, server_auth_env) -> None:
    status = asyncio.run(codex_server_auth.server_auth_status(_row(db_session)))

    assert status.auth_file_exists is False
    assert status.importable is False
    assert "No server Codex login" in (status.error or "")


def test_server_auth_status_malformed_file(db_session: Session, server_auth_env) -> None:
    server_auth_env.write_text("not json", encoding="utf-8")

    status = asyncio.run(codex_server_auth.server_auth_status(_row(db_session)))

    assert status.auth_file_exists is True
    assert status.importable is False
    assert "auth file is invalid" in (status.error or "")


def test_server_auth_status_valid_file(db_session: Session, server_auth_env) -> None:
    server_auth_env.write_text(_auth_blob(), encoding="utf-8")

    status = asyncio.run(codex_server_auth.server_auth_status(_row(db_session)))

    assert status.importable is True
    assert status.plan_type == "plus"
    assert status.expires_at is not None
    assert status.error is None
    assert "codex login --device-auth" in status.login_command


def test_server_auth_status_refreshes_expired_file(
    db_session: Session, server_auth_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_auth_env.write_text(_auth_blob(expired=True), encoding="utf-8")
    fresh_access = _access_token()

    async def _refresh(
        session: CodexSession,
        *,
        force: bool = False,
        persist=None,
        http_client=None,
    ) -> CodexSession:
        refreshed = replace(
            session,
            access_token=fresh_access,
            refresh_token="rotated-refresh",
            expires_at=datetime.now(UTC) + timedelta(hours=2),
            last_refresh=datetime.now(UTC),
        )
        if persist is not None:
            await persist(refreshed)
        return refreshed

    monkeypatch.setattr(codex_server_auth, "refresh_session", _refresh)

    status = asyncio.run(codex_server_auth.server_auth_status(_row(db_session)))

    assert status.importable is True
    data = json.loads(server_auth_env.read_text(encoding="utf-8"))
    assert data["tokens"]["access_token"] == fresh_access
    assert data["tokens"]["refresh_token"] == "rotated-refresh"


def test_load_server_session_force_refreshes_valid_file(
    server_auth_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_auth_env.write_text(_auth_blob(), encoding="utf-8")
    fresh_access = _access_token()
    seen_force: list[bool] = []

    async def _refresh(
        session: CodexSession,
        *,
        force: bool = False,
        persist=None,
        http_client=None,
    ) -> CodexSession:
        seen_force.append(force)
        refreshed = replace(
            session,
            access_token=fresh_access,
            refresh_token="rotated-refresh",
            expires_at=datetime.now(UTC) + timedelta(hours=2),
            last_refresh=datetime.now(UTC),
        )
        if persist is not None:
            await persist(refreshed)
        return refreshed

    monkeypatch.setattr(codex_server_auth, "refresh_session", _refresh)

    session = asyncio.run(codex_server_auth.load_server_session())

    assert seen_force == [True]
    assert session.access_token == fresh_access
    data = json.loads(server_auth_env.read_text(encoding="utf-8"))
    assert data["tokens"]["access_token"] == fresh_access
    assert data["tokens"]["refresh_token"] == "rotated-refresh"


def test_server_auth_status_reports_refresh_failure(
    db_session: Session, server_auth_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_auth_env.write_text(_auth_blob(expired=True), encoding="utf-8")

    async def _refresh(*_args, **_kwargs) -> CodexSession:
        raise AuthExpiredError("401 Unauthorized")

    monkeypatch.setattr(codex_server_auth, "refresh_session", _refresh)

    status = asyncio.run(codex_server_auth.server_auth_status(_row(db_session)))

    assert status.importable is False
    assert "codex login --device-auth" in (status.error or "")
