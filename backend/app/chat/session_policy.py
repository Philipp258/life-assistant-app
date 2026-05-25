"""Per-kind chat session policy.

Task chat and main chat run on one turn engine (`app.chat.runner`).
The only real differences between them live here, so the runner, the
router, and the system-prompt builder ask this module instead of
branching on `kind` inline:

- which system-prompt preamble the agent gets (main = conversational
  GENERAL_PROMPT; task = autonomous TASK_PROMPT) — see
  `app.agent.build_system_prompt`,
- whether a session *consumes* task-terminal events (only the singleton
  main session does; tasks only produce them),
- whether a session is *wake-eligible* right now (task: assignee/done/
  do_at gate via `runner.should_start_task`; main: only if it has
  undrained terminal events to act on).

Terminal tool gating (`complete`/`reassign`/`reschedule` are task-only)
already lives in `app.agent.tools._task_scope`; push behaviour ("a text
message in the main session notifies the user") already lives in
`app.chat.service.save_new_messages`. This module is just the seam the
turn engine reads.
"""

from __future__ import annotations

from typing import Literal

from app.chat.models import ChatSession

Kind = Literal["main", "task"]


def resolve_kind(chat: ChatSession | None) -> Kind:
    """Classify a session. `task_id IS NULL` (or `kind='main'`) → main.

    Defensive against the historical `kind` backfill: a row that is not
    task-bound is the main chat regardless of the stored discriminator.
    """
    if chat is None:
        return "main"
    if chat.kind == "main" or chat.task_id is None:
        return "main"
    return "task"


def consumes_terminal_events(chat: ChatSession | None) -> bool:
    """Whether this session drains task-terminal events on each turn.

    Only the singleton main session does — that is what makes a task
    handoff surface in the user's conversation. Task chats only emit
    handoffs; they never consume.
    """
    return resolve_kind(chat) == "main"
