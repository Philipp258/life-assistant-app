"""Constants, templates, and pure helpers used across the runner.

This module has no side effects and no DB access. Keep new additions
likewise side-effect-free so it can be imported cheaply from anywhere
inside the runner package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic_ai.messages import ModelRequest, SystemPromptPart

from app.datetime_utils import utc_now
from app.tasks.models import Task
from pydantic_ai.messages import UserPromptPart


WakeOutcome = Literal[
    "terminated",
    "stalled",
    "errored",
    "no_task",
    "already_done",
    "paused",
    "scheduled",
    "restarted",
    "completed",  # a main wake ran a turn
    "no_events",  # a main wake found nothing to drain
]


@dataclass
class RunResult:
    outcome: WakeOutcome
    new_message_count: int = 0


class _StaleTaskInputRestart(Exception):
    """Internal non-error signal: restart the task wake with fresh chat history."""

    def __init__(self, new_message_count: int) -> None:
        super().__init__("task input changed during runner loop")
        self.new_message_count = new_message_count


# Streak at which we stop trusting the agent to converge on its own and
# flip the task back to the user with an explanatory message.
STALL_ESCALATION_THRESHOLD = 3

# Streak at which we stop retrying a task whose wakes keep raising and
# hand it back to the user. Mirrors STALL_ESCALATION_THRESHOLD; the
# watchdog backoff (`_gap_for`) handles the first two.
ERROR_ESCALATION_THRESHOLD = 3

# Streak at which a task that keeps deferring itself is treated as an
# infinite reschedule loop. High enough for long implementation-agent
# workflows that legitimately poll/check back many times.
RESCHEDULE_ESCALATION_THRESHOLD = 50

STALL_REMINDER_TEXT = (
    "[runner reminder] Your previous turn finished without ending the task. "
    "End this wake with the terminal task move that matches reality: "
    "`complete_task(handoff=...)`, `reassign_task(assignee='user', handoff=...)`, "
    "or `reschedule_task(do_at=..., handoff=...)`. The handoff is hidden "
    "context for the main-chat assistant, not a direct user message."
)

ESCALATION_MESSAGE = (
    "{assistant_name} tried this task three times in a row without converging on "
    "complete, reassign, or reschedule. Handing it back to you so we "
    "don't loop. Reply in main chat or in the task chat when you'd like "
    "another attempt; if you reply in main chat, the assistant can relay the "
    "instruction back into this task."
)

ERROR_RETRY_TEMPLATE = (
    "{assistant_name} hit an error while running this task. I'll retry automatically "
    "with backoff.\n\nError: `{error}`"
)

# Main chat has no autonomous retry loop; on a failed turn we surface
# the error once so the user can simply send again (vs. silently
# losing the turn).
MAIN_ERROR_TEMPLATE = (
    "Something went wrong handling that — your message wasn't answered. "
    "Please try again.\n\nError: `{error}`"
)

ERROR_PAUSE_TASK_CHAT_TEMPLATE = (
    "{assistant_name} hit errors {count} times in a row while running this task, so "
    "I'm pausing it instead of retrying forever. Reply in main chat or "
    "in this task after the underlying problem is fixed.\n\nLast error: `{error}`"
)

RESCHEDULE_PAUSE_TASK_CHAT_TEMPLATE = (
    "{assistant_name} rescheduled this task {count} times in a row, so I'm pausing it "
    "instead of deferring forever. Reply in main chat or in this task when you'd like "
    "another attempt."
)

TERMINAL_TASK_TOOL_NAMES = {
    "ask_user_choice",
    "complete_task",
    "reassign_task",
    "reschedule_task",
}


def _sanitize_error_text(exc: BaseException, *, max_len: int = 200) -> str:
    """Concise one-line representation of an exception for chat surfaces.

    Stack traces stay in the logger; users only see `Type: message` so
    the chat doesn't get clobbered with internals. Newlines are
    collapsed to keep the rendered card single-paragraph.
    """
    msg = str(exc).strip().splitlines()
    head = msg[0] if msg else ""
    summary = f"{type(exc).__name__}: {head}" if head else type(exc).__name__
    if len(summary) > max_len:
        summary = summary[: max_len - 1].rstrip() + "…"
    return summary


def _bootstrap_prompt(task: Task) -> str:
    """Synthetic user prompt sent on the first wake of a freshly created task.

    Most chat models (including Z.AI's glm-* family) reject requests that
    have only a system message and no user content. When the task chat is
    empty, we inject a user prompt built from the task's title and
    description so the agent has something concrete to respond to. The
    saved history then contains the bootstrap prompt + the agent's reply,
    and subsequent wakes can run normally.
    """
    parts = [
        f"Begin task #{task.id}: {task.title}",
    ]
    if task.description and task.description.strip():
        parts.append(f"Notes: {task.description.strip()}")
    parts.append(
        "Work in this task chat. Share useful progress here, not by editing "
        "the task description. When done, blocked on the user, or waiting on "
        "time, use the matching terminal task tool with a handoff for the "
        "main-chat assistant. The terminal tools operate on this chat's task "
        "implicitly and do not post directly to main chat."
    )
    return "\n\n".join(parts)


def _build_stall_reminder() -> ModelRequest:
    """Synthetic system-prompt request used to nudge a stalled agent.

    A `ModelRequest` carrying a single `SystemPromptPart`. Not
    persisted — injected per wake when `task.consecutive_stalls > 0`.
    """
    return ModelRequest(parts=[SystemPromptPart(content=STALL_REMINDER_TEXT)])


def _build_bootstrap_request(task: Task) -> ModelRequest:
    """ModelRequest carrying the synthetic bootstrap user prompt."""
    return ModelRequest(
        parts=[UserPromptPart(content=_bootstrap_prompt(task), timestamp=utc_now())]
    )
