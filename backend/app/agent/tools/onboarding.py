"""Pydantic AI tool: mark the user as onboarded.

Called by the assistant once the onboarding ritual is finished — both
core memory files have been populated and the user seems satisfied.
After this call, `users_service.is_onboarding()` returns False and
`build_system_prompt` switches the main session back to the normal
preamble on the next turn.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from app.agent.deps import AgentDeps


def do_mark_onboarded() -> dict[str, Any]:
    from app.db import SessionLocal
    from app.users.service import mark_onboarded

    with SessionLocal() as db:
        wrote = mark_onboarded(db)
    return {"ok": True, "already_onboarded": not wrote}


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool_plain
    def mark_onboarded() -> dict[str, Any]:
        """Stamp the user as onboarded. Call only after writing both
        core memory files (about_user.md and behavior.md, the latter
        with `**Name:** <name>` as its first line) and confirming with
        the user that setup is finished.

        Idempotent — calling twice returns `already_onboarded: true`
        on the second call without changing state.
        """
        return do_mark_onboarded()
