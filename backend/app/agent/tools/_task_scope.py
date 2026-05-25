"""Helpers that scope tools to the chat session's bound task.

Used to gate `complete_task` and `reassign_task` so they're only
available — and only operate on — the task this chat belongs to.
Without this, a general chat agent could (and did) hallucinate a
task_id and complete unrelated tasks on the user's behalf.
"""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

from app.agent.deps import AgentDeps
from app.chat.models import ChatSession
from app.db import SessionLocal


def current_task_id(ctx: RunContext[AgentDeps]) -> int | None:
    """Resolve the task id this chat belongs to, or None for general chats."""
    sid = ctx.deps.session_id if ctx.deps is not None else None
    if sid is None:
        return None
    with SessionLocal() as db:
        chat = db.get(ChatSession, sid)
        if chat is None:
            return None
        return chat.task_id


def only_in_task_chat(
    ctx: RunContext[AgentDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Prepare hook: hide the tool entirely outside a task chat.

    Returning None tells pydantic-ai to skip the tool for this run, so
    the model never sees it as an option in non-task contexts.
    """
    if current_task_id(ctx) is None:
        return None
    return tool_def
