"""Task-terminal event feed for the main chat.

A "terminal event" is the hidden `<task_handoff>` row a task records
when it completes, blocks back to the user, or reschedules itself (see
`app.chat.service.save_task_handoff`, written by the terminal task tools
and the runner's stall/error escalations). The main session drains
these events on its next turn.

State is a single high-water cursor per consuming session
(`ChatSession.event_cursor_id`): exactly-once and restart-safe because
the cursor lives in the DB and only advances after a turn that actually
saw the events.

Shape: drained handoffs are delivered as one synthetic *user-role*
report appended to the turn's history (context only — never persisted).
Ending the history on a user turn is a valid provider request shape and
gives the model an unambiguous "respond to THIS" target. The report is
explicitly framed as not-from-the-user and "don't re-answer earlier
conversation" so an autonomous wake addresses only these updates
instead of continuing the prior thread.

Silence: a drain turn runs with the `do_nothing` output tool
(`SILENCE_OUTPUT`). When the drained updates are routine internal
status the user did not ask to track, the model calls `do_nothing` to
end the turn with no message, and `app.chat.runner` maps that to a
cursor-only commit (no row, no push). It surfaces only what the user
needs awareness of or a decision on; when genuinely unsure it surfaces
rather than swallow.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel
from pydantic_ai import ToolOutput
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    SystemPromptPart,
    UserPromptPart,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.models import ChatSession, Message
from app.chat.service import extract_task_handoff_text, parse_message
from app.chat.session_policy import consumes_terminal_events
from app.tasks.models import Task


class StaySilent(BaseModel):
    """Output marker: the model triaged the task report and chose silence.

    No fields — the model just calls the tool. `app.chat.runner` checks
    `result.output` against this type to take the cursor-only path.
    """


# Offered as a per-run output type only on main event-drain turns
# (`app.chat.runner`), never on normal chat turns. Calling it ends the
# run (pydantic-ai output-tool semantics), so the model cannot also emit
# a visible reply — silence is framework-guaranteed, not heuristic.
SILENCE_OUTPUT = ToolOutput(
    StaySilent,
    name="do_nothing",
    description=(
        "End this turn with no main-chat message. Call when the drained "
        "task updates are routine internal status the user did not ask to "
        "track and that need no awareness or decision."
    ),
)


def _handoff_text_from_row(row: Message) -> str | None:
    """Pull the handoff body out of a persisted message row, if it is one."""
    msg = parse_message(row)
    if msg is None:
        return None
    for part in msg.parts:
        if not isinstance(part, SystemPromptPart):
            continue
        handoff = extract_task_handoff_text(part.content)
        if handoff is not None:
            return handoff
    return None


def _task_status(task: Task | None) -> str:
    if task is None:
        return "no longer exists"
    if task.is_done:
        return "completed"
    if task.assignee == "user":
        return "handed back to you (needs your input or a decision)"
    if task.do_at is not None:
        return f"rescheduled to {task.do_at.isoformat()}"
    return "stopped"


def _format_entry(task: Task | None, handoff: str) -> str:
    body = handoff.strip() or "(no explicit handoff text)"
    if task is None:
        return f"task: (deleted)\nstatus: {_task_status(task)}\n\nhandoff:\n{body}"
    lines = [
        f"task_id: {task.id}",
        f"title: {task.title}",
        f"status: {_task_status(task)}",
        f"link: /tasks/{task.id}",
    ]
    if task.goal_id is not None:
        lines.extend(
            [
                f"goal_id: {task.goal_id}",
                f"goal_title: {task.goal.title if task.goal is not None else '(unknown)'}",
                f"goal_link: /goals/{task.goal_id}",
            ]
        )
    lines.extend(["", "handoff:", body])
    return "\n".join(lines)


def _build_injection(entries: list[str]) -> list[ModelMessage]:
    """A synthetic user-role report of what the background tasks did.

    Trailing user turn = a valid request and a clear triage target.
    Framed as not-from-the-user and "don't re-answer earlier
    conversation" so an autonomous wake addresses only these updates.
    The model either replies (surfaced to main chat) or calls
    `do_nothing` (silent — `SILENCE_OUTPUT`)."""
    body = "\n\n---\n\n".join(entries)
    content = (
        "[Automated background-task report — not a message from the user]\n\n"
        f"{body}\n\n"
        "Triage this for the user's main chat — it is not a new user "
        "request. Surface, in your own voice, what they need awareness of "
        "or a decision on: finished results they asked for, blockers, "
        "questions, failures, meaningful status changes. If the update is "
        "only routine internal status the user did not ask to track (a "
        "recurrence tick, a wait or reschedule, polling), call `do_nothing` "
        "to end the turn with no message. When genuinely unsure, surface "
        "it. If you surface it, write a direct main-chat reply to the user, "
        "not a status report about the user or the task. Use natural "
        "first-/second-person phrasing, keep it restrained, and turn the "
        "handoff into what the user can think about next. Either way, do "
        "not re-answer or continue earlier conversation — only address "
        "these task updates."
    )
    return [ModelRequest(parts=[UserPromptPart(content=content)])]


def _candidate_rows(session: Session, *, after_id: int) -> list[Message]:
    # `id > after_id` is the (indexed PK) bound, so this only scans
    # rows newer than the consumer's cursor — typically a handful. The
    # `<task_handoff>` predicate itself lives in JSON and can't be
    # indexed, but the id bound keeps the candidate set tiny. Fine at
    # single-user scale.
    return list(
        session.scalars(
            select(Message)
            .join(ChatSession, Message.session_id == ChatSession.id)
            .where(
                Message.id > after_id,
                Message.archived_at.is_(None),
                Message.kind == "request",
                ChatSession.task_id.is_not(None),
            )
            .order_by(Message.id)
        )
    )


def latest_terminal_event_id(session: Session) -> int | None:
    """Highest message id that is a task-terminal handoff, or None.

    Used by the runner/watchdog to decide whether the main session still
    has work to drain ("cursor < latest").
    """
    highest: int | None = None
    for row in _candidate_rows(session, after_id=0):
        if _handoff_text_from_row(row) is not None:
            highest = row.id
    return highest


def has_undrained_events(session: Session, consuming_session_id: int) -> bool:
    consumer = session.get(ChatSession, consuming_session_id)
    if consumer is None or not consumes_terminal_events(consumer):
        return False
    cursor = consumer.event_cursor_id or 0
    for row in _candidate_rows(session, after_id=cursor):
        if _handoff_text_from_row(row) is not None:
            return True
    return False


def drain_terminal_events(
    session: Session, consuming_session_id: int
) -> tuple[list[ModelMessage], list[Message]]:
    """Pull every task-terminal event newer than the consumer's cursor.

    Returns the synthetic injection messages to append to the turn's
    history plus the `Message` rows processed, so the caller advances the
    cursor only *after* a turn that actually saw them (exactly-once).
    Empty for any session that does not consume events (every task chat).
    """
    consumer = session.get(ChatSession, consuming_session_id)
    if not consumes_terminal_events(consumer):
        return [], []
    assert consumer is not None
    cursor = consumer.event_cursor_id or 0

    seen: list[Message] = []
    entries: list[str] = []
    for row in _candidate_rows(session, after_id=cursor):
        handoff = _handoff_text_from_row(row)
        if handoff is None:
            continue
        chat = session.get(ChatSession, row.session_id)
        task = (
            session.get(Task, chat.task_id)
            if chat is not None and chat.task_id is not None
            else None
        )
        entries.append(_format_entry(task, handoff))
        seen.append(row)

    if not seen:
        return [], []
    return _build_injection(entries), seen


def advance_event_cursor(
    session: Session,
    consuming_session_id: int,
    *,
    seen: Iterable[Message],
    commit: bool = True,
) -> None:
    """Move the consumer's high-water cursor past every processed row.

    `commit=False` only stages the cursor field on `session`; the caller
    is then responsible for committing it. The runner uses this to make
    the cursor advance atomic with the turn's persisted reply (one
    transaction) — otherwise a process exit between "reply committed"
    and "cursor committed" re-drains the same handoff and the model
    answers it twice.
    """
    highest = 0
    for m in seen:
        if m.id > highest:
            highest = m.id
    if highest == 0:
        return
    consumer = session.get(ChatSession, consuming_session_id)
    if consumer is None:
        return
    if consumer.event_cursor_id is None or highest > consumer.event_cursor_id:
        consumer.event_cursor_id = highest
        if commit:
            session.commit()
