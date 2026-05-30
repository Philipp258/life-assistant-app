"""DB helpers for tasks. No FastAPI concerns here."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.chat.models import ChatSession, Message
from app.chat import pubsub
from app.datetime_utils import normalize_to_naive_utc, utc_now
from app.notifications import service as notify_service
from app.tasks.models import Assignee, IntervalUnit, Task
from app.tasks.schemas import TaskCreate, TaskUpdate, task_to_read
from app.tasks.task_log import (
    allocate_task_log_line,
    is_recurring_assistant_task,
)
from app.tasks.taxonomy import status_predicate

# Shapes mirror `app.saved_task_views.schemas` so saved-view filter blobs
# round-trip cleanly through this listing path.
TaskStatus = Literal["open", "scheduled", "waiting", "done"]
DueWindow = Literal["today", "week"]


_INTERVAL_TO_TIMEDELTA = {
    "hour": lambda n: timedelta(hours=n),
    "day": lambda n: timedelta(days=n),
    "week": lambda n: timedelta(weeks=n),
}


def _publish_task_upsert(task: Task) -> None:
    """Publish the current task row to listeners already tailing its chat."""
    pubsub.publish(
        task.chat_session_id,
        {
            "type": "task_upsert",
            "session_id": task.chat_session_id,
            "task_id": task.id,
            "task": task_to_read(task).model_dump(mode="json"),
        },
    )


def _publish_task_delete(*, task_id: int, chat_session_id: int) -> None:
    pubsub.publish(
        chat_session_id,
        {
            "type": "task_delete",
            "session_id": chat_session_id,
            "task_id": task_id,
        },
    )


def _next_do_at(prev_do_at: datetime | None, unit: IntervalUnit, count: int) -> datetime:
    """Anchor on the previous do_at if set so cadence is preserved across
    late completions; otherwise anchor on now (best-effort for tasks that
    were never scheduled in the first place)."""
    base = prev_do_at if prev_do_at is not None else utc_now()
    return base + _INTERVAL_TO_TIMEDELTA[unit](count)


def _ensure_goal_exists(session: Session, goal_id: int | None) -> int | None:
    if goal_id is None:
        return None
    from app.goals.models import Goal

    if session.get(Goal, goal_id) is None:
        raise ValueError(f"unknown goal_id: {goal_id}")
    return goal_id


def _append_goal_event(
    session: Session,
    goal_id: int | None,
    *,
    kind: str,
    body: str,
    task_id: int,
) -> None:
    if goal_id is None:
        return
    from app.goals import service as goals_service

    goals_service.append_goal_event(
        session,
        goal_id,
        kind=kind,
        body=body,
        task_id=task_id,
        commit=False,
    )


def _today_window() -> tuple[datetime, datetime]:
    """Naive-UTC [start_of_today, end_of_today]. Mirrors the storage shape."""
    now = utc_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1) - timedelta(microseconds=1)
    return start, end


def _week_window() -> tuple[datetime, datetime]:
    """Naive-UTC [start_of_today, end_of_today+6d]. Inclusive of today."""
    start, _ = _today_window()
    end = start + timedelta(days=7) - timedelta(microseconds=1)
    return start, end


def _last_msg_subq():
    """Subquery: last non-archived message timestamp per chat session.

    Built fresh per call (subquery objects shouldn't be shared across
    statements). Shared by the activity-ordered open listing and the
    reflection agent's `list_tasks_with_activity` so the "what counts as
    activity" definition stays in one place.
    """
    return (
        select(
            Message.session_id.label("session_id"),
            func.max(Message.created_at).label("last_msg_at"),
        )
        .where(Message.archived_at.is_(None))
        .group_by(Message.session_id)
        .subquery()
    )


def _apply_common_filters(
    stmt: Select[Any],
    *,
    assignee: Assignee | None,
    due: DueWindow | None,
) -> Select[Any]:
    """Assignee / due-window filters shared by the open and done listing paths.
    Status predicates stay inline in `list_tasks` (legacy path only)."""
    if assignee:
        stmt = stmt.where(Task.assignee == assignee)
    if due == "today":
        start, end = _today_window()
        stmt = stmt.where(or_(Task.due_at.between(start, end), Task.do_at.between(start, end)))
    elif due == "week":
        start, end = _week_window()
        stmt = stmt.where(or_(Task.due_at.between(start, end), Task.do_at.between(start, end)))
    return stmt


def _encode_done_cursor(completed_at: datetime, task_id: int) -> str:
    raw = f"{completed_at.isoformat()}|{task_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_done_cursor(cursor: str) -> tuple[datetime, int]:
    """Decode an opaque keyset cursor. Raises ValueError on any tampering
    so the router can answer 422 instead of 500."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.rsplit("|", 1)
        return datetime.fromisoformat(ts_str), int(id_str)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("invalid cursor") from exc


def list_tasks(
    session: Session,
    *,
    assignee: Assignee | None = None,
    statuses: list[TaskStatus] | None = None,
    due: DueWindow | None = None,
    done: bool | None = None,
) -> list[Task]:
    """List tasks.

    `done` controls the lifecycle slice and ordering:

    - ``None``  – legacy: every task, open-before-done, do_at then
      recency. Kept stable for old callers / saved views.
    - ``False`` – open tasks only, ordered by **last activity** desc
      (max of task.updated_at and last non-archived message). This is
      the two-axis list's open feed.
    - ``True``  – done tasks only, completed_at desc (unpaginated; the
      paginated tail goes through `list_done_tasks`).
    """
    stmt = _apply_common_filters(select(Task), assignee=assignee, due=due)
    if statuses:
        stmt = stmt.where(status_predicate(list(statuses)))

    if done is True:
        stmt = stmt.where(Task.is_done.is_(True)).order_by(Task.completed_at.desc(), Task.id.desc())
        return list(session.scalars(stmt))

    if done is False:
        sub = _last_msg_subq()
        activity = case(
            (sub.c.last_msg_at > Task.updated_at, sub.c.last_msg_at),
            else_=Task.updated_at,
        )
        stmt = (
            stmt.where(Task.is_done.is_(False))
            .outerjoin(sub, Task.chat_session_id == sub.c.session_id)
            .order_by(activity.desc(), Task.id.desc())
        )
        return list(session.scalars(stmt))

    stmt = stmt.order_by(
        Task.is_done.asc(),
        Task.do_at.is_(None).asc(),
        Task.do_at.asc(),
        Task.updated_at.desc(),
        Task.id.desc(),
    )
    return list(session.scalars(stmt))


def list_done_tasks(
    session: Session,
    *,
    assignee: Assignee | None = None,
    due: DueWindow | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[Task], str | None]:
    """Keyset-paginated done tail, `completed_at desc, id desc`.

    The done archive is unbounded (thousands over time); the open feed is
    not, so only this path paginates. Returns ``(rows, next_cursor)`` —
    `next_cursor` is None once the archive is exhausted.
    """
    stmt = _apply_common_filters(
        select(Task).where(Task.is_done.is_(True)),
        assignee=assignee,
        due=due,
    )
    if cursor:
        c_ts, c_id = _decode_done_cursor(cursor)
        stmt = stmt.where(
            or_(
                Task.completed_at < c_ts,
                and_(Task.completed_at == c_ts, Task.id < c_id),
            )
        )
    stmt = stmt.order_by(Task.completed_at.desc(), Task.id.desc()).limit(limit + 1)
    rows = list(session.scalars(stmt))
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        # completed_at is always set on done tasks (stamped in update_task).
        assert last.completed_at is not None
        next_cursor = _encode_done_cursor(last.completed_at, last.id)
    return rows, next_cursor


def list_tasks_with_activity(
    session: Session,
) -> list[tuple[Task, datetime]]:
    """Tasks paired with their last activity timestamp.

    Activity = MAX(task.updated_at, MAX(messages.created_at) on the task's
    chat session). Lets the reflection agent (and anyone else who wants
    "what changed recently") sort/filter without a separate column.
    """
    last_msg_subq = _last_msg_subq()
    stmt = (
        select(Task, last_msg_subq.c.last_msg_at)
        .outerjoin(
            last_msg_subq,
            Task.chat_session_id == last_msg_subq.c.session_id,
        )
        .order_by(
            Task.is_done.asc(),
            Task.do_at.is_(None).asc(),
            Task.do_at.asc(),
            Task.updated_at.desc(),
            Task.id.desc(),
        )
    )
    out: list[tuple[Task, datetime]] = []
    for task, last_msg_at in session.execute(stmt).all():
        activity = task.updated_at
        if last_msg_at is not None and last_msg_at > activity:
            activity = last_msg_at
        out.append((task, activity))
    return out


def get_task(session: Session, task_id: int) -> Task | None:
    return session.get(Task, task_id)


def create_task(session: Session, data: TaskCreate) -> Task:
    """Create a task and its 1-to-1 chat session in one go.

    The chat is inserted first (with `task_id` left NULL) so the Task
    row can satisfy the NOT NULL `chat_session_id` invariant in one
    insert; the back-pointer is wired right after. The reverse FK has
    a CASCADE so deleting either end drops the pair.
    """
    goal_id = _ensure_goal_exists(session, data.goal_id)

    chat = ChatSession(title=data.title[:128])
    session.add(chat)
    session.flush()  # populate chat.id

    # Recurring assistant routines get a durable task-log identity so the
    # `Task Log/<line>.md` knowledge note can accumulate learning across
    # cycles. One-shot jobs and user-owned tasks have no recurrence to
    # carry context across, so they get None.
    task_log_line = (
        allocate_task_log_line(session, title=data.title)
        if is_recurring_assistant_task(
            assignee=data.assignee,
            interval_unit=data.interval_unit,
            interval_count=data.interval_count,
        )
        else None
    )

    task = Task(
        title=data.title,
        description=data.description,
        assignee=data.assignee,
        chat_session_id=chat.id,
        do_at=normalize_to_naive_utc(data.do_at),
        due_at=normalize_to_naive_utc(data.due_at),
        interval_unit=data.interval_unit,
        interval_count=data.interval_count,
        goal_id=goal_id,
        task_log_line=task_log_line,
    )
    session.add(task)
    session.flush()  # populate task.id
    _append_goal_event(
        session,
        goal_id,
        kind="task_linked",
        body=f"Task linked: {task.title}",
        task_id=task.id,
    )

    chat.task_id = task.id
    session.commit()
    session.refresh(task)
    _publish_task_upsert(task)

    from app.chat import runner

    if runner.should_start_task(task):
        runner.schedule_wake(chat.id)

    return task


def update_task(
    session: Session,
    task_id: int,
    patch: TaskUpdate,
) -> Task | None:
    task = get_task(session, task_id)
    if task is None:
        return None
    data = patch.model_dump(exclude_unset=True)
    for key in ("do_at", "due_at", "completed_at", "due_notified_at"):
        if key in data:
            data[key] = normalize_to_naive_utc(data[key])
    if "goal_id" in data:
        data["goal_id"] = _ensure_goal_exists(session, data["goal_id"])
    prev_done = task.is_done
    prev_assignee = task.assignee
    prev_do_at = task.do_at
    prev_goal_id = task.goal_id
    for key, value in data.items():
        setattr(task, key, value)
    if task.interval_unit is None or task.interval_count is None:
        task.task_log_line = None
    # If this update tipped the task into "recurring assistant" without
    # an existing identity, assign one now so the first cycle already
    # writes to a stable log file. We never repoint an existing line
    # while recurrence remains — title or schedule edits leave identity
    # unchanged. Clearing recurrence turns the row back into a one-shot
    # task, so it drops the log line too.
    if task.task_log_line is None and is_recurring_assistant_task(
        assignee=task.assignee,
        interval_unit=task.interval_unit,
        interval_count=task.interval_count,
    ):
        task.task_log_line = allocate_task_log_line(
            session, title=task.title, exclude_task_id=task.id
        )
    if "due_at" in data:
        # Rescheduling clears the due-date dedupe so the scheduler can
        # fire again at the new deadline.
        task.due_notified_at = None
    just_completed = False
    just_reopened = False
    if "is_done" in data:
        if task.is_done and not prev_done:
            task.completed_at = utc_now()
            just_completed = True
        elif not task.is_done and prev_done:
            task.completed_at = None
            just_reopened = True

    spawned: Task | None = None
    if just_completed and task.interval_unit is not None and task.interval_count is not None:
        spawned = _spawn_next_recurrence(session, task, prev_do_at)

    if "goal_id" in data and task.goal_id != prev_goal_id:
        _append_goal_event(
            session,
            prev_goal_id,
            kind="task_unlinked",
            body=f"Task unlinked: {task.title}",
            task_id=task.id,
        )
        _append_goal_event(
            session,
            task.goal_id,
            kind="task_linked",
            body=f"Task linked: {task.title}",
            task_id=task.id,
        )
    if just_completed:
        _append_goal_event(
            session,
            task.goal_id,
            kind="task_completed",
            body=f"Task completed: {task.title}",
            task_id=task.id,
        )
    elif just_reopened:
        _append_goal_event(
            session,
            task.goal_id,
            kind="task_reopened",
            body=f"Task reopened: {task.title}",
            task_id=task.id,
        )

    handed_to_user = prev_assignee == "assistant" and task.assignee == "user"
    handed_to_assistant = prev_assignee != "assistant" and task.assignee == "assistant"

    if handed_to_assistant and not task.is_done:
        # User explicitly re-engaged the assistant on this task. Wipe the
        # wake-health counters so any prior stall streak / outage
        # backoff doesn't carry over into the new attempt.
        task.consecutive_stalls = 0
        task.consecutive_errors = 0
        task.consecutive_reschedules = 0

    if just_completed:
        task.consecutive_stalls = 0
        task.consecutive_errors = 0
        task.consecutive_reschedules = 0

    session.commit()
    session.refresh(task)
    if spawned is not None:
        session.refresh(spawned)
    _publish_task_upsert(task)

    # If this update flipped the task into the assistant's hands and it's
    # not already done, kick off the autonomous runner. Imported here so
    # the runner's transitive imports (agent / model build) don't load on
    # every `tasks.service` import.
    if handed_to_assistant and not task.is_done:
        from app.chat import runner

        runner.schedule_wake(task.chat_session_id)

    if handed_to_user:
        _fire_task_assigned_push(task)

    return task


def _fire_task_assigned_push(task: Task) -> None:
    """Schedule a Web Push for a task that was just handed back to the user.

    `update_task` is sync, so delegate the sync-to-async bridge to the
    notifications service and keep this hook focused on the payload.
    """
    notify_service.schedule_notify(
        event_type="task_assigned",
        title=task.title,
        body="Task is on you.",
        url=f"/tasks/{task.id}",
        tag=f"task_assigned:{task.id}",
    )


def run_task_now(session: Session, task_id: int) -> Task | None:
    """Make an assistant task runnable immediately and nudge the runner.

    Sets `do_at` to now (overriding a future schedule) and wakes the
    runner if the task is eligible. For recurring tasks, the next cycle
    is spawned off the just-set `do_at` on completion, so cadence shifts
    forward — the user opted in by pressing "Run now".

    Returns the task on success, or None if not found / not eligible
    (done, or not assigned to the assistant).
    """
    task = get_task(session, task_id)
    if task is None:
        return None
    if task.is_done or task.assignee != "assistant":
        return None
    task.do_at = utc_now()
    session.commit()
    session.refresh(task)
    _publish_task_upsert(task)

    from app.chat import runner

    if runner.should_start_task(task):
        runner.schedule_wake(task.chat_session_id)
    return task


def reschedule_task(
    session: Session,
    task_id: int,
    do_at: datetime,
) -> Task | None:
    """Defer a task by setting its `do_at` to a future moment.

    Counts as a terminal move for the autonomous runner: once `do_at`
    is in the future, `list_in_flight_tasks` skips the task until that
    time. The chat is preserved, so the agent resumes the same thread
    on the next wake. For recurring tasks, the next-cycle anchor shifts
    accordingly via `_next_do_at` (cadence drifts with the new do_at).

    User-facing notification of the deferral is the main session's
    job: it drains the recorded handoff as a task-terminal event
    (`app.chat.events`) on its next turn, not a side effect here.
    """
    task = get_task(session, task_id)
    if task is None:
        return None
    task.do_at = normalize_to_naive_utc(do_at)
    session.commit()
    session.refresh(task)
    _publish_task_upsert(task)
    return task


def _spawn_next_recurrence(session: Session, completed: Task, prev_do_at: datetime | None) -> Task:
    """Create the next instance of a recurring task once its predecessor
    is marked done. Each instance gets a fresh ChatSession so the agent
    starts cleanly without dragging the prior cycle's history along.

    Stall/error counters are not copied — the new row defaults to 0,
    giving each cycle a clean wake-health slate.
    """
    assert completed.interval_unit is not None and completed.interval_count is not None
    next_do_at = _next_do_at(prev_do_at, completed.interval_unit, completed.interval_count)
    new_chat = ChatSession(title=completed.title[:128])
    session.add(new_chat)
    session.flush()
    new_task = Task(
        title=completed.title,
        description=completed.description,
        assignee=completed.assignee,
        chat_session_id=new_chat.id,
        do_at=next_do_at,
        interval_unit=completed.interval_unit,
        interval_count=completed.interval_count,
        goal_id=completed.goal_id,
        # Carry the task-log identity forward so cycle N+1 reads/writes
        # the same `Task Log/<line>.md` note as cycle N.
        task_log_line=completed.task_log_line,
    )
    session.add(new_task)
    session.flush()
    new_chat.task_id = new_task.id
    return new_task


def previous_completed_sibling(session: Session, task: Task) -> Task | None:
    """Latest completed sibling of a recurring assistant routine.

    Recurrence cycles share `task_log_line` (carried forward by
    `_spawn_next_recurrence`), so it doubles as the identity used to walk
    a routine's history. Excludes `task` itself. Returns None for
    non-recurring tasks or when no prior cycle has finished.
    """
    if task.task_log_line is None:
        return None
    stmt = (
        select(Task)
        .where(Task.task_log_line == task.task_log_line)
        .where(Task.id != task.id)
        .where(Task.is_done.is_(True))
        .where(Task.completed_at.is_not(None))
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def delete_task(session: Session, task_id: int) -> bool:
    """Delete a task; its 1-to-1 chat session (and messages) cascade."""
    task = get_task(session, task_id)
    if task is None:
        return False
    chat_session_id = task.chat_session_id
    session.delete(task)
    session.commit()
    _publish_task_delete(task_id=task_id, chat_session_id=chat_session_id)
    return True
