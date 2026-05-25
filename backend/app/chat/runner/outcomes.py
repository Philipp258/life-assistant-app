"""Post-wake classification and escalation.

After `run_session_turn` returns (or raises) on a task wake,
`_persist_wake_outcome` reloads the task, increments the right counter,
and decides whether to drop a chat message / hand the task back to the
user. Main-chat surfacing of escalations rides the task-terminal event
drain (`app.chat.events`).
"""

from __future__ import annotations

import logging

from pydantic_ai.messages import ModelResponse, TextPart
from sqlalchemy.orm import Session

from app.chat.service import save_new_messages, save_task_handoff
from app.datetime_utils import normalize_to_naive_utc, utc_now
from app.db import SessionLocal
from app.knowledge.identity import resolve_assistant_name
from app.tasks.models import Task
from app.tasks.schemas import TaskUpdate
from app.tasks.service import update_task

from .messages import (
    ERROR_ESCALATION_THRESHOLD,
    ERROR_PAUSE_TASK_CHAT_TEMPLATE,
    ERROR_RETRY_TEMPLATE,
    ESCALATION_MESSAGE,
    RESCHEDULE_ESCALATION_THRESHOLD,
    RESCHEDULE_PAUSE_TASK_CHAT_TEMPLATE,
    STALL_ESCALATION_THRESHOLD,
    WakeOutcome,
)

logger = logging.getLogger(__name__)


def _persist_wake_outcome(
    task_id: int,
    *,
    errored: bool = False,
    error_text: str | None = None,
) -> WakeOutcome:
    """Classify a finished wake and persist counter changes.

    Called once per task wake from `wake_session`. Reloads the task in a
    fresh session so we see any field mutations the agent made via tools
    (e.g. `complete_task` flipping `is_done`, `reschedule_task` setting
    `do_at`). When the stall streak crosses the escalation threshold,
    flips the task to `assignee="user"` via `update_task` and drops the
    explanation message into the task chat (the user sees it where the
    work happened) plus a hidden handoff the main session drains next.

    On hard errors, appends a sanitized error message to the task chat
    so the user sees the failure where the work happens. After
    `ERROR_ESCALATION_THRESHOLD` consecutive errors the task is also
    handed back to the user with a final pause notice in the task chat;
    main-chat surfacing rides the same task-terminal event drain.
    """
    now = utc_now()
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        if task is None:
            return "no_task"

        if errored:
            task.consecutive_errors += 1
            outcome: WakeOutcome = "errored"
        elif task.is_done or task.assignee == "user":
            task.consecutive_stalls = 0
            task.consecutive_errors = 0
            task.consecutive_reschedules = 0
            outcome = "terminated"
        elif task.do_at is not None and normalize_to_naive_utc(task.do_at) > now:
            task.consecutive_stalls = 0
            task.consecutive_errors = 0
            task.consecutive_reschedules += 1
            outcome = "terminated"
        else:
            task.consecutive_stalls += 1
            outcome = "stalled"
        session.commit()

        if outcome == "errored":
            _handle_error_outcome(session, task_id, error_text or "")

        if (
            outcome == "terminated"
            and task.assignee == "assistant"
            and not task.is_done
            and task.do_at is not None
            and normalize_to_naive_utc(task.do_at) > now
            and task.consecutive_reschedules >= RESCHEDULE_ESCALATION_THRESHOLD
        ):
            _handle_reschedule_limit_outcome(session, task_id)

        if outcome == "stalled" and task.consecutive_stalls >= STALL_ESCALATION_THRESHOLD:
            logger.warning(
                "runner: escalating task %d to user after %d consecutive stalls",
                task_id,
                task.consecutive_stalls,
            )
            chat_session_id = task.chat_session_id
            if chat_session_id is not None:
                body = ESCALATION_MESSAGE.format(assistant_name=resolve_assistant_name())
                save_new_messages(
                    session,
                    chat_session_id,
                    [ModelResponse(parts=[TextPart(content=body)])],
                )
                save_task_handoff(session, chat_session_id, body)
            update_task(session, task_id, TaskUpdate(assignee="user"))
    return outcome


def _handle_reschedule_limit_outcome(session: Session, task_id: int) -> None:
    task = session.get(Task, task_id)
    if task is None or task.chat_session_id is None:
        return

    body = RESCHEDULE_PAUSE_TASK_CHAT_TEMPLATE.format(
        assistant_name=resolve_assistant_name(),
        count=task.consecutive_reschedules,
    )
    save_new_messages(
        session,
        task.chat_session_id,
        [ModelResponse(parts=[TextPart(content=body)])],
    )
    save_task_handoff(session, task.chat_session_id, body)
    logger.warning(
        "runner: pausing task %d after %d consecutive reschedules",
        task_id,
        task.consecutive_reschedules,
    )
    update_task(session, task_id, TaskUpdate(assignee="user"))


def _handle_error_outcome(session: Session, task_id: int, error_text: str) -> None:
    """Surface a runner error in the task chat (and escalate at threshold).

    Caller has already committed the counter increment, so we re-read
    `consecutive_errors` for the branch decision. Below threshold: drop
    a one-line "I'll retry" message into the task chat. At threshold:
    drop a final "pausing this" message into the task chat and hand the
    task back to the user via `update_task`. Main-chat surfacing of the
    pause rides the task-terminal event drain (`app.chat.events`).
    """
    task = session.get(Task, task_id)
    if task is None:
        return

    chat_session_id = task.chat_session_id
    error_label = error_text or "unknown error"
    assistant_name = resolve_assistant_name()

    if task.consecutive_errors < ERROR_ESCALATION_THRESHOLD:
        body = ERROR_RETRY_TEMPLATE.format(assistant_name=assistant_name, error=error_label)
        save_new_messages(
            session,
            chat_session_id,
            [ModelResponse(parts=[TextPart(content=body)])],
        )
        return

    body = ERROR_PAUSE_TASK_CHAT_TEMPLATE.format(
        assistant_name=assistant_name, count=task.consecutive_errors, error=error_label
    )
    save_new_messages(
        session,
        chat_session_id,
        [ModelResponse(parts=[TextPart(content=body)])],
    )
    save_task_handoff(session, chat_session_id, body)
    logger.warning(
        "runner: pausing task %d after %d consecutive errors",
        task_id,
        task.consecutive_errors,
    )
    update_task(session, task_id, TaskUpdate(assignee="user"))
