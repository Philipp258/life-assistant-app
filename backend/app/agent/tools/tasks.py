"""Pydantic AI tools for Tasks.

Logic lives in plain `do_*` functions so unit tests can exercise them
without spinning up an Agent. `register(agent)` wires them onto a Pydantic
AI `Agent`.

Tools the agent gets:
- create_task (any chat) — defaults assignee='assistant'.
- list_tasks (any chat) — supports `since` and `title` filters; surfaces
  `last_activity_at` so the agent can spot tasks with recent activity
  (used by the weekly reflection).
- get_task (any chat) — full detail for a single task.
- update_task (any chat) — edit task fields (title, description, do_at,
  due_at, interval, is_done, assignee). Assignment and completion flow
  through the same service side-effects as the task-local terminal tools.
- delete_task (any chat) — drop a task and its chat history.
- complete_task / reassign_task / reschedule_task (task chat only) —
  operate implicitly on the current chat's task. Hidden from non-task
  chats via a prepare hook so the general chat agent can never
  accidentally complete a task on the user's behalf.

These terminal tools have NO direct main-chat side effect. Each terminal
tool requires a plain-text handoff for the main-chat assistant; after the
wake stops, that agent is woken with the handoff and decides whether to
say anything in main chat.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic_ai import Agent, RunContext

from app.agent.deps import AgentDeps
from app.agent.tools._paging import normalize_page, paginate
from app.agent.tools._task_scope import current_task_id, only_in_task_chat
from app.datetime_utils import normalize_to_naive_utc, serialize_utc, utc_now
from app.db import SessionLocal
from app.tasks import service
from app.tasks.models import Task
from app.tasks.schemas import (
    Assignee,
    IntervalUnit,
    TaskCreate,
    TaskUpdate,
    task_to_read,
)
from app.tasks.task_log import task_log_path


def _task_log_for_agent(task: Any) -> str | None:
    line = getattr(task, "task_log_line", None)
    return task_log_path(line) if line else None


def _summarize(
    task: Task,
    *,
    last_activity_at: datetime | None = None,
    include_description: bool = True,
) -> dict[str, Any]:
    task_log = _task_log_for_agent(task)
    read = task_to_read(task)
    out: dict[str, Any] = {
        "id": read.id,
        "title": read.title,
        "is_done": read.is_done,
        "assignee": read.assignee,
        "labels": read.labels,
        "state": read.state,
        "kind": read.kind,
        "do_at": serialize_utc(read.do_at),
        "due_at": serialize_utc(read.due_at),
        "interval_unit": read.interval_unit,
        "interval_count": read.interval_count,
        "chat_session_id": read.chat_session_id,
        "completed_at": serialize_utc(read.completed_at),
    }
    if include_description:
        # Omitted from list rows: a long description duplicated across
        # every row floods context. `get_task` returns it in full.
        out["description"] = read.description
    if task_log is not None:
        out["task_log"] = task_log
    if last_activity_at is not None:
        out["last_activity_at"] = serialize_utc(last_activity_at)
    return out


def do_create_task(
    title: str,
    description: str | None = None,
    assignee: Assignee = "assistant",
    labels: list[str] | None = None,
    do_at: datetime | None = None,
    due_at: datetime | None = None,
    interval_unit: IntervalUnit | None = None,
    interval_count: int | None = None,
) -> dict[str, Any]:
    # Ergonomics: if a unit was supplied but count wasn't, assume 1.
    if interval_unit is not None and interval_count is None:
        interval_count = 1
    data = TaskCreate(
        title=title,
        description=description,
        assignee=assignee,
        labels=labels or [],
        do_at=do_at,
        due_at=due_at,
        interval_unit=interval_unit,
        interval_count=interval_count,
    )
    with SessionLocal() as session:
        try:
            task = service.create_task(session, data)
        except ValueError as exc:
            return {"error": str(exc)}
        return _summarize(task)


LIST_TASKS_PAGE_DEFAULT = 50
# A model-supplied `limit` above this is clamped down so one call can't
# flood context regardless of the arg.
LIST_TASKS_PAGE_MAX = 200


def do_list_tasks(
    is_done: bool | None = None,
    assignee: Assignee | None = None,
    labels: list[str] | None = None,
    since: datetime | None = None,
    title: str | None = None,
    offset: int = 0,
    limit: int = LIST_TASKS_PAGE_DEFAULT,
) -> dict[str, Any]:
    # `since` may arrive timezone-aware (pydantic-ai parses ISO strings
    # with `Z` / offset as aware), while DB timestamps are naive UTC.
    # Coerce to the naive-UTC shape so the comparison below never mixes.
    since_naive = normalize_to_naive_utc(since)
    label_filter = set(labels) if labels else None
    with SessionLocal() as session:
        rows = service.list_tasks_with_activity(session)
        # Snapshot label slugs while the session is still open so we can
        # filter outside the session without triggering detached-instance
        # lazy loads.
        items = [(t, activity, {label.slug for label in t.labels}) for t, activity in rows]
    title_match = title.lower() if title else None
    matched = [
        _summarize(t, last_activity_at=activity, include_description=False)
        for t, activity, task_labels in items
        if (is_done is None or t.is_done == is_done)
        and (assignee is None or t.assignee == assignee)
        and (label_filter is None or task_labels & label_filter)
        and (since_naive is None or activity >= since_naive)
        and (title_match is None or title_match in t.title.lower())
    ]
    safe_offset, safe_limit = normalize_page(
        offset, limit, default_limit=LIST_TASKS_PAGE_DEFAULT, max_limit=LIST_TASKS_PAGE_MAX
    )
    page = paginate(matched, safe_offset, safe_limit)
    page["tasks"] = page.pop("items")
    return page


def do_get_task(task_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        task = service.get_task(session, task_id)
        if task is None:
            return {"error": "task not found", "task_id": task_id}
        task_log = _task_log_for_agent(task)
        read = task_to_read(task)
    out = read.model_dump(mode="json")
    if task_log is not None:
        out["task_log"] = task_log
    return out


_UNSET: Any = object()


def do_update_task(
    task_id: int,
    *,
    title: str | Any = _UNSET,
    description: str | None | Any = _UNSET,
    is_done: bool | Any = _UNSET,
    assignee: Assignee | Any = _UNSET,
    labels: list[str] | Any = _UNSET,
    do_at: datetime | None | Any = _UNSET,
    due_at: datetime | None | Any = _UNSET,
    interval_unit: IntervalUnit | None | Any = _UNSET,
    interval_count: int | None | Any = _UNSET,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if title is not _UNSET:
        fields["title"] = title
    if description is not _UNSET:
        fields["description"] = description
    if is_done is not _UNSET:
        fields["is_done"] = is_done
    if assignee is not _UNSET:
        fields["assignee"] = assignee
    if labels is not _UNSET:
        fields["labels"] = labels
    if do_at is not _UNSET:
        fields["do_at"] = do_at
    if due_at is not _UNSET:
        fields["due_at"] = due_at
    if interval_unit is not _UNSET:
        fields["interval_unit"] = interval_unit
    if interval_count is not _UNSET:
        fields["interval_count"] = interval_count
    if not fields:
        return {
            "error": "update_task requires at least one field to change",
            "task_id": task_id,
        }
    try:
        patch = TaskUpdate(**fields)
    except ValueError as e:
        return {"error": str(e), "task_id": task_id}
    with SessionLocal() as session:
        task = service.update_task(session, task_id, patch)
        if task is None:
            return {"error": "task not found", "task_id": task_id}
        return _summarize(task)


def _clean_handoff(handoff: str) -> str | None:
    text = (handoff or "").strip()
    return text or None


def _handoff_required(task_id: int) -> dict[str, Any]:
    return {
        "error": "a non-empty handoff is required",
        "task_id": task_id,
    }


def _already_terminal_result(task: Task) -> dict[str, Any]:
    """Tool result for duplicate terminal calls in the same/already-ended task.

    Terminal tools are side-effecting: their handoff row is the event the
    main chat drains. A model can still continue after a terminal tool
    return and try another terminal call in the same agent turn, so guard
    at the DB boundary and make later calls explicit no-ops.
    """
    result = _summarize(task)
    result["ok"] = False
    result["already_terminal"] = True
    result["message"] = "task is already in a terminal state; no new handoff was recorded"
    return result


def _has_recorded_handoff(session: Any, task: Task) -> bool:
    """Whether a terminal tool already recorded a handoff for this
    task's current chat (cycle). That — not assignee/do_at on its own —
    is what makes a *subsequent* terminal call in the same agent turn a
    duplicate. Reassigning is the pause/resume mechanism, so a real
    assignee change must still go through (handled by the callers); only
    redundant repeats are blocked.
    """
    from app.chat.service import latest_task_handoff

    return latest_task_handoff(session, task.chat_session_id) is not None


def _has_active_terminal_handoff(session: Any, task: Task) -> bool:
    if not _has_recorded_handoff(session, task):
        return False
    if task.assignee == "user":
        return True
    if task.do_at is not None and normalize_to_naive_utc(task.do_at) > utc_now():
        return True
    return False


def do_complete_task(task_id: int, handoff: str) -> dict[str, Any]:
    text = _clean_handoff(handoff)
    if text is None:
        return _handoff_required(task_id)
    with SessionLocal() as session:
        existing = service.get_task(session, task_id)
        if existing is None:
            return {"error": "task not found", "task_id": task_id}
        # Duplicate completion (the model called complete_task again in
        # the same turn after it already ended the task) is the bug we
        # guard. Completing a not-yet-ended task — even one assigned to
        # the user — is legitimate.
        if existing.is_done or _has_active_terminal_handoff(session, existing):
            return _already_terminal_result(existing)

        task = service.update_task(session, task_id, TaskUpdate(is_done=True))
        if task is None:
            return {"error": "task not found", "task_id": task_id}
        from app.chat.service import save_task_handoff

        save_task_handoff(session, task.chat_session_id, text)
        return _summarize(task)


def do_reassign_task(task_id: int, assignee: Assignee, handoff: str) -> dict[str, Any]:
    text = _clean_handoff(handoff)
    if text is None:
        return _handoff_required(task_id)
    with SessionLocal() as session:
        existing = service.get_task(session, task_id)
        if existing is None:
            return {"error": "task not found", "task_id": task_id}
        # Reassign is pause/resume — a real assignee CHANGE must always
        # go through (e.g. flipping back to 'assistant' to resume).
        # Only a redundant reassign to the SAME assignee after a handoff
        # was already recorded, or acting on a done task, is a no-op.
        if existing.is_done or (
            existing.assignee == assignee and _has_recorded_handoff(session, existing)
        ):
            return _already_terminal_result(existing)

        task = service.update_task(session, task_id, TaskUpdate(assignee=assignee))
        if task is None:
            return {"error": "task not found", "task_id": task_id}
        from app.chat.service import save_task_handoff

        save_task_handoff(session, task.chat_session_id, text)
        return _summarize(task)


def do_delete_task(task_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        ok = service.delete_task(session, task_id)
        if not ok:
            return {"error": "task not found", "task_id": task_id}
        return {"deleted": True, "task_id": task_id}


def do_reschedule_task(task_id: int, do_at: datetime, handoff: str) -> dict[str, Any]:
    text = _clean_handoff(handoff)
    if text is None:
        return _handoff_required(task_id)
    do_at = normalize_to_naive_utc(do_at)
    if do_at <= utc_now():
        return {
            "error": (
                "reschedule_task requires a future `do_at` — passing a past "
                "time would re-fire on the next watchdog tick"
            ),
            "task_id": task_id,
        }
    with SessionLocal() as session:
        existing = service.get_task(session, task_id)
        if existing is None:
            return {"error": "task not found", "task_id": task_id}
        if existing.is_done or _has_active_terminal_handoff(session, existing):
            return _already_terminal_result(existing)

        task = service.reschedule_task(session, task_id, do_at)
        if task is None:
            return {"error": "task not found", "task_id": task_id}
        from app.chat.service import save_task_handoff

        save_task_handoff(session, task.chat_session_id, text)
        return _summarize(task)


def _update_task_tool_kwargs(
    *,
    title: str | None = None,
    description: str | None = None,
    is_done: bool | None = None,
    assignee: Assignee | None = None,
    labels: list[str] | None = None,
    do_at: datetime | None = None,
    due_at: datetime | None = None,
    interval_unit: IntervalUnit | None = None,
    interval_count: int | None = None,
    clear_description: bool = False,
    clear_do_at: bool = False,
    clear_due_at: bool = False,
    clear_recurrence: bool = False,
) -> dict[str, Any]:
    if clear_description and description is not None:
        raise ValueError("pass either description or clear_description, not both")
    if clear_do_at and do_at is not None:
        raise ValueError("pass either do_at or clear_do_at, not both")
    if clear_due_at and due_at is not None:
        raise ValueError("pass either due_at or clear_due_at, not both")
    if clear_recurrence and (interval_unit is not None or interval_count is not None):
        raise ValueError("pass either recurrence fields or clear_recurrence, not both")

    kwargs: dict[str, Any] = {}
    if title is not None:
        kwargs["title"] = title
    if description is not None:
        kwargs["description"] = description
    elif clear_description:
        kwargs["description"] = None
    if is_done is not None:
        kwargs["is_done"] = is_done
    if assignee is not None:
        kwargs["assignee"] = assignee
    if labels is not None:
        kwargs["labels"] = labels
    if do_at is not None:
        kwargs["do_at"] = do_at
    elif clear_do_at:
        kwargs["do_at"] = None
    if due_at is not None:
        kwargs["due_at"] = due_at
    elif clear_due_at:
        kwargs["due_at"] = None
    if clear_recurrence:
        kwargs["interval_unit"] = None
        kwargs["interval_count"] = None
    else:
        if interval_unit is not None:
            kwargs["interval_unit"] = interval_unit
        if interval_count is not None:
            kwargs["interval_count"] = interval_count
    return kwargs


def register(agent: Agent[AgentDeps, Any]) -> None:
    """Attach the Tasks tools to the given Pydantic AI agent.

    `create_task`, `list_tasks`, `get_task`, `update_task`, and
    `delete_task` are always available. `complete_task`,
    `reassign_task`, and `reschedule_task` are gated by
    `only_in_task_chat`: they only exist inside the chat that owns a
    task and always operate on that task. The general chat agent can
    still coordinate tasks explicitly via `update_task`, but it must
    name the task id instead of acting on an implicit current task.
    """

    @agent.tool
    def create_task(
        ctx: RunContext[AgentDeps],
        title: str,
        assignee: Assignee,
        description: str | None = None,
        labels: list[str] | None = None,
        do_at: datetime | None = None,
        due_at: datetime | None = None,
        interval_unit: IntervalUnit | None = None,
        interval_count: int | None = None,
    ) -> dict[str, Any]:
        """Create a new task.

        `assignee` is required: 'user' if the user has to do or unblock
        it, 'assistant' if you should do the next step.

        Task descriptions are rendered as Markdown in the UI; use concise
        Markdown for structure (lists, links, code, headings) when helpful.

        Field semantics:
        - `labels` (optional list of slugs): tags applied to the task.
          Unknown slugs cause the call to error.
        - `do_at` (ISO datetime): START trigger. The autonomous runner
          wakes an assistant-assigned task only once `do_at <= now`.
        - `due_at` (ISO datetime): DEADLINE. User-facing only — the
          runner ignores it.
        - `interval_unit` ('hour'|'day'|'week') + `interval_count` (>=1):
          recurrence. Pass both together. Pass `do_at` alongside to
          anchor the first run.
        """
        return do_create_task(
            title=title,
            description=description,
            assignee=assignee,
            labels=labels,
            do_at=do_at,
            due_at=due_at,
            interval_unit=interval_unit,
            interval_count=interval_count,
        )

    @agent.tool_plain
    def list_tasks(
        is_done: bool | None = None,
        assignee: Assignee | None = None,
        labels: list[str] | None = None,
        since: datetime | None = None,
        title: str | None = None,
        offset: int = 0,
        limit: int = LIST_TASKS_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        """List tasks, optionally filtered, one page at a time.

        - `is_done`: only completed (True) or only open (False).
        - `assignee`: 'user' or 'assistant'.
        - `labels`: only tasks carrying at least one of these label slugs
          (OR semantics). Unknown slugs are silently ignored.
        - `since`: only tasks with activity at or after this timestamp.
          Activity = the later of the task's last update or the most
          recent message in its chat session. Useful for "what's
          happened lately" — e.g. the weekly reflection passes the
          previous reflection's completed_at to scope the review.
        - `title`: case-insensitive substring match. Useful for finding
          previous instances of recurring tasks (e.g. all "Weekly
          reflection" rows) by name.
        - `offset` / `limit`: page through results (default 50 per
          page, 200 max — a larger `limit` is clamped). Pass the
          returned `next_offset` as `offset` for the next page.

        Returns `{tasks, total, offset, limit, has_more, next_offset}`.
        List rows omit `description` to stay compact — call
        `get_task(id)` for the full description and remaining detail,
        and `list_chat_messages(session_id)` to read what actually
        happened in a task's chat. Each row includes `kind` (computed
        UI label) and `last_activity_at` so you can sort by recency.
        """
        return do_list_tasks(
            is_done=is_done,
            assignee=assignee,
            labels=labels,
            since=since,
            title=title,
            offset=offset,
            limit=limit,
        )

    @agent.tool_plain
    def get_task(task_id: int) -> dict[str, Any]:
        """Read full detail for a single task.

        Returns public task fields — including `chat_session_id`,
        `created_at`, `completed_at`, `due_at`, recurrence, and a
        routine's `task_log` knowledge path when it has one — which
        `list_tasks` may omit. Pair with
        `list_chat_messages(chat_session_id)` to read what happened in
        the task's chat.
        """
        return do_get_task(task_id)

    @agent.tool_plain
    def update_task(
        task_id: int,
        title: str | None = None,
        description: str | None = None,
        is_done: bool | None = None,
        assignee: Assignee | None = None,
        labels: list[str] | None = None,
        do_at: datetime | None = None,
        due_at: datetime | None = None,
        interval_unit: IntervalUnit | None = None,
        interval_count: int | None = None,
        clear_description: bool = False,
        clear_do_at: bool = False,
        clear_due_at: bool = False,
        clear_recurrence: bool = False,
    ) -> dict[str, Any]:
        """Edit fields on an existing task.

        Pass only the fields you want to change. Omitted fields are left
        untouched. `labels`, when passed, REPLACES the task's full label
        set with the given list of slugs (pass `[]` to drop all labels).
        Task descriptions are rendered as Markdown in the UI; use concise
        Markdown for structure when helpful. To clear `interval_unit`
        and `interval_count`, pass them together (the schema rejects
        half-cleared recurrence), or pass `clear_recurrence=True`.
        Use `clear_description=True`, `clear_do_at=True`, and
        `clear_due_at=True` to clear those nullable fields. `is_done=True` marks the task done;
        `is_done=False` reopens it. `assignee='assistant'` hands the
        task to the assistant and schedules the autonomous runner when eligible;
        `assignee='user'` pauses assistant work and puts the ball in
        the user's court.

        From main chat, when the user gives an answer or direction for a
        waiting task, use `relay_to_task(task_id, note)` — it writes the
        instruction into the task's chat and resumes it. From inside a
        task chat, prefer `complete_task`,
        `reassign_task`, and `reschedule_task` for terminal moves because
        they operate implicitly on the current task.
        """
        try:
            kwargs = _update_task_tool_kwargs(
                title=title,
                description=description,
                is_done=is_done,
                assignee=assignee,
                labels=labels,
                do_at=do_at,
                due_at=due_at,
                interval_unit=interval_unit,
                interval_count=interval_count,
                clear_description=clear_description,
                clear_do_at=clear_do_at,
                clear_due_at=clear_due_at,
                clear_recurrence=clear_recurrence,
            )
        except ValueError as exc:
            return {"error": str(exc), "task_id": task_id}
        return do_update_task(task_id, **kwargs)

    @agent.tool_plain
    def delete_task(task_id: int) -> dict[str, Any]:
        """Permanently delete a task and its chat history.

        Use only for tasks that are wrong (mistaken, obsolete,
        duplicate). For finishing work use `complete_task`.
        """
        return do_delete_task(task_id)

    @agent.tool(prepare=only_in_task_chat)
    def complete_task(ctx: RunContext[AgentDeps], handoff: str) -> dict[str, Any]:
        """Mark *this* task done.

        Only available inside the chat for a task. Operates implicitly on
        the task this chat belongs to — there is no task_id argument so
        you cannot accidentally complete a different task.

        For a recurring task this completes the *current* cycle; the
        runner auto-spawns the next instance with a fresh chat.

        `handoff` is required: a concise plain-text note for the
        main-chat assistant about what happened and what, if anything,
        the user may need to know next. This is not posted directly to
        main chat; that agent is woken with the handoff and decides
        whether to say anything.
        """
        tid = current_task_id(ctx)
        if tid is None:
            return {"error": "complete_task is only available inside a task chat"}
        return do_complete_task(tid, handoff=handoff)

    @agent.tool(prepare=only_in_task_chat)
    def reassign_task(
        ctx: RunContext[AgentDeps],
        assignee: Assignee,
        handoff: str,
    ) -> dict[str, Any]:
        """Hand *this* task over.

        Only available inside the chat for a task. Operates implicitly
        on the current task.

        - `assignee='user'`: pause yourself and put the ball in the
          user's court. The user re-engages by replying in the task
          chat (or by reassigning back).
        - `assignee='assistant'`: take the task back (rare; usually the
          user re-engages instead).

        `handoff` is required: explain why control is changing hands.
        When handing to the user, include the question, blocker, or
        decision needed. This is hidden context for the main-chat
        assistant, which decides whether and how to surface it in main
        chat.
        """
        tid = current_task_id(ctx)
        if tid is None:
            return {"error": "reassign_task is only available inside a task chat"}
        return do_reassign_task(task_id=tid, assignee=assignee, handoff=handoff)

    @agent.tool(prepare=only_in_task_chat)
    def reschedule_task(
        ctx: RunContext[AgentDeps],
        do_at: datetime,
        handoff: str,
    ) -> dict[str, Any]:
        """Defer *this* task until `do_at`. Terminal move.

        Use when the right next move is to wait — "check back tomorrow",
        "Friday morning", "in an hour". Sets `do_at` so the autonomous
        runner skips this task until that time, then re-wakes you. The
        chat is preserved; you'll resume with full history.

        Counts as a terminal move: ends the current wake cleanly, like
        `complete_task` and `reassign_task`. For recurring tasks, this
        defers the current cycle and shifts the next-cycle anchor
        accordingly. Do NOT pass a `do_at` in the past.

        `handoff` is required: explain why the task is waiting until
        then and what the main-chat assistant may need to know. This
        is not posted directly to main chat.
        """
        tid = current_task_id(ctx)
        if tid is None:
            return {"error": "reschedule_task is only available inside a task chat"}
        return do_reschedule_task(task_id=tid, do_at=do_at, handoff=handoff)
