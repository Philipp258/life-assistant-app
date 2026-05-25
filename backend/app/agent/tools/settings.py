"""Agent tools for DB-backed runtime app settings.

The assistant can inspect and overwrite supported app settings via
these tools — values are plaintext and not treated as secrets.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from app.agent.deps import AgentDeps
from app.db import SessionLocal
from app.settings import service


def get_runtime_settings() -> dict[str, str]:
    with SessionLocal() as db:
        return service.list_runtime_settings(db)


def set_runtime_setting(key: str, value: str) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            saved = service.set_runtime_setting(db, key=key, value=value)
        except ValueError as exc:
            return {"error": str(exc)}
    return {"key": key, "value": saved}


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool_plain
    def get_app_settings() -> dict[str, str]:
        """Return assistant-visible app settings. Plaintext values.

        Missing/cleared values come back as an empty string.
        """
        return get_runtime_settings()

    @agent.tool_plain
    def set_app_setting(key: str, value: str) -> dict[str, Any]:
        """Set an assistant-visible app setting.

        Supported keys include `brave_api_key` and `vad_timeout_ms`.
        Passing an empty string clears the setting. Returns `{key,
        value}` on success or `{error: ...}` for an unsupported key.
        """
        return set_runtime_setting(key, value)
