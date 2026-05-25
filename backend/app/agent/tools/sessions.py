"""Main → task relay.

`relay_to_task` is the one cross-session write: from main chat, push the
user's answer/instruction for a blocked task back into that task and
resume it. It is task-scoped on purpose — it resolves the task's chat
from a `task_id`, so it can never post into main or an arbitrary
session (the old generic `post_message_to_session` could, and the agent
misused it to surface task news instead of just replying). The relayed
note is plain history in the task chat, stamped with the originating
session for UI provenance; the task agent treats it as user intent on
its next run.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelResponse, TextPart

from app.agent.deps import AgentDeps
from app.chat.service import save_new_messages
from app.db import SessionLocal


def do_relay_to_task(
    task_id: int,
    note: str,
    *,
    source_session_id: int | None,
) -> dict[str, Any]:
    """Write `note` into `task_id`'s chat and resume the task.

    Returns `{ok, task_id}` or `{error}`. Resuming = assignee back to
    'assistant' so the runner picks it up; the task sees `note` as
    user intent in its history on the next run.
    """
    from app.chat import runner
    from app.tasks import service as tasks_service
    from app.tasks.models import Task
    from app.tasks.schemas import TaskUpdate

    text = (note or "").strip()
    if not text:
        return {"error": "relay_to_task requires a non-empty note", "task_id": task_id}

    with SessionLocal() as session:
        task = session.get(Task, task_id)
        if task is None:
            return {"error": "task not found", "task_id": task_id}
        target_session_id = task.chat_session_id
        if source_session_id is not None and source_session_id == target_session_id:
            return {"error": "cannot relay into the current task's own chat", "task_id": task_id}

        save_new_messages(
            session,
            target_session_id,
            [ModelResponse(parts=[TextPart(content=text)])],
            source_session_id=source_session_id,
        )
        tasks_service.update_task(session, task_id, TaskUpdate(assignee="assistant"))

    runner.schedule_wake(target_session_id)
    return {"ok": True, "task_id": task_id, "resumed": True}


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool
    def relay_to_task(
        ctx: RunContext[AgentDeps],
        task_id: int,
        note: str,
    ) -> dict[str, Any]:
        """Relay the user's answer/instruction for a task back into it
        and resume it.

        From main chat, when the user answers, corrects, or redirects a
        task: pass that task's `task_id` (from the task update or
        `get_task`) and a concise `note` of what the user said. It writes
        the note into the task's chat and flips the task to
        assignee='assistant' so it continues. If which task the user
        means is ambiguous, ask them first.
        """
        source = ctx.deps.session_id if ctx.deps is not None else None
        return do_relay_to_task(task_id, note, source_session_id=source)
