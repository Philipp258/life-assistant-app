"""Server-side Codex CLI auth discovery and import helpers."""

from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.agent.providers.codex_auth import (
    AuthExpiredError,
    AuthInvalidError,
    CodexSession,
    load_session_from_json,
    refresh_session,
    session_to_json,
)
from app.provider_settings import service
from app.provider_settings.models import ProviderSettings

SERVICE_HOME = Path("/root")
DEFAULT_CODEX_HOME = SERVICE_HOME / ".codex"


class ServerAuthError(Exception):
    """Server Codex auth cannot currently be imported."""


@dataclass(frozen=True)
class ServerAuthStatus:
    codex_cli_installed: bool
    auth_file: str
    auth_file_exists: bool
    importable: bool
    configured: bool
    expires_at: datetime | None
    plan_type: str | None
    error: str | None
    login_command: str
    status_command: str


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else DEFAULT_CODEX_HOME


def auth_file_path() -> Path:
    return codex_home() / "auth.json"


def _command_prefix() -> str:
    parts = ["env", f"HOME={SERVICE_HOME}"]
    configured_home = os.environ.get("CODEX_HOME")
    if configured_home:
        parts.append(f"CODEX_HOME={configured_home}")
    return " ".join(shlex.quote(part) for part in parts)


def login_command() -> str:
    return f"{_command_prefix()} codex login --device-auth"


def status_command() -> str:
    return f"{_command_prefix()} codex login status"


def codex_cli_installed() -> bool:
    return shutil.which("codex") is not None


async def _persist_to_auth_file(path: Path, session: CodexSession) -> None:
    path.write_text(session_to_json(session), encoding="utf-8")
    path.chmod(0o600)


async def load_server_session(*, force_refresh: bool = True) -> CodexSession:
    if not codex_cli_installed():
        raise ServerAuthError(
            "Codex CLI is not installed. Rerun the installer or install it with "
            "`npm install -g @openai/codex`."
        )

    path = auth_file_path()
    if not path.exists():
        raise ServerAuthError(
            "No server Codex login was found. SSH to the server as root, run "
            "the login command shown in Settings, then check again."
        )

    try:
        blob = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ServerAuthError(f"Could not read Codex auth file: {exc}") from exc

    try:
        session = load_session_from_json(blob)
    except AuthInvalidError as exc:
        raise ServerAuthError(
            "The server Codex auth file is invalid. Rerun the login command shown "
            "in Settings, then check again."
        ) from exc

    try:
        return await refresh_session(
            session,
            force=force_refresh,
            persist=lambda refreshed: _persist_to_auth_file(path, refreshed),
        )
    except AuthExpiredError as exc:
        raise ServerAuthError(str(exc)) from exc
    except OSError as exc:
        raise ServerAuthError(f"Could not update Codex auth file after refresh: {exc}") from exc


async def server_auth_status(row: ProviderSettings) -> ServerAuthStatus:
    installed = codex_cli_installed()
    path = auth_file_path()
    exists = path.exists()
    configured = service.codex_session_from_row(row) is not None
    session: CodexSession | None = None
    error: str | None = None

    if installed and exists:
        try:
            session = await load_server_session(force_refresh=False)
        except ServerAuthError as exc:
            error = str(exc)
    elif not installed:
        error = (
            "Codex CLI is not installed. Rerun the installer or install it with "
            "`npm install -g @openai/codex`."
        )
    else:
        error = (
            "No server Codex login was found. SSH to the server as root, run "
            "the login command, then check again."
        )

    return ServerAuthStatus(
        codex_cli_installed=installed,
        auth_file=str(path),
        auth_file_exists=exists,
        importable=session is not None,
        configured=configured,
        expires_at=session.expires_at if session is not None else None,
        plan_type=session.plan_type if session is not None else None,
        error=error,
        login_command=login_command(),
        status_command=status_command(),
    )
