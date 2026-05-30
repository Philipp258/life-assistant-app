"""Pydantic AI tools for durable goals.

Goals are lightweight project/outcome containers. They do not have their
own chat; main chat coordinates them, and concrete work happens in linked
tasks.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from app.agent.deps import AgentDeps
from app.agent.tools._paging import normalize_page, paginate
from app.db import SessionLocal
from app.goals.models import Goal
from app.goals import service
from app.goals.schemas import (
    GoalCreate,
    GoalEventCreate,
    GoalEventKind,
    GoalUpdate,
    goal_event_to_read,
    goal_to_detail,
    goal_to_read,
)


LIST_GOALS_PAGE_DEFAULT = 30
LIST_GOALS_PAGE_MAX = 100


def _goal_dict(goal: Goal, *, detail: bool = False) -> dict[str, Any]:
    read = goal_to_detail(goal) if detail else goal_to_read(goal)
    return read.model_dump(mode="json")


def do_create_goal(
    title: str,
    description: str | None = None,
    task_ids: list[int] | None = None,
) -> dict[str, Any]:
    with SessionLocal() as session:
        try:
            goal = service.create_goal(
                session,
                GoalCreate(
                    title=title,
                    description=description,
                    task_ids=task_ids or [],
                ),
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return _goal_dict(goal)


def do_list_goals(
    is_done: bool | None = None,
    title: str | None = None,
    offset: int = 0,
    limit: int = LIST_GOALS_PAGE_DEFAULT,
) -> dict[str, Any]:
    title_match = title.lower() if title else None
    safe_offset, safe_limit = normalize_page(
        offset,
        limit,
        default_limit=LIST_GOALS_PAGE_DEFAULT,
        max_limit=LIST_GOALS_PAGE_MAX,
    )
    with SessionLocal() as session:
        rows = service.list_goals(session, done=is_done)
        matched = [
            _goal_dict(goal)
            for goal in rows
            if title_match is None or title_match in goal.title.lower()
        ]
    page = paginate(matched, safe_offset, safe_limit)
    page["goals"] = page.pop("items")
    return page


def do_get_goal(goal_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        goal = service.get_goal(session, goal_id)
        if goal is None:
            return {"error": "goal not found", "goal_id": goal_id}
        return _goal_dict(goal, detail=True)


class _UnsetType:
    _instance: "_UnsetType | None" = None

    def __new__(cls) -> "_UnsetType":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance


_UNSET = _UnsetType()


def do_update_goal(
    goal_id: int,
    *,
    title: str | _UnsetType = _UNSET,
    description: str | None | _UnsetType = _UNSET,
    is_done: bool | _UnsetType = _UNSET,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if not isinstance(title, _UnsetType):
        fields["title"] = title
    if not isinstance(description, _UnsetType):
        fields["description"] = description
    if not isinstance(is_done, _UnsetType):
        fields["is_done"] = is_done
    if not fields:
        return {"error": "update_goal requires at least one field to change", "goal_id": goal_id}
    try:
        patch = GoalUpdate(**fields)
    except ValueError as exc:
        return {"error": str(exc), "goal_id": goal_id}
    with SessionLocal() as session:
        goal = service.update_goal(session, goal_id, patch)
        if goal is None:
            return {"error": "goal not found", "goal_id": goal_id}
        return _goal_dict(goal, detail=True)


def do_append_goal_event(
    goal_id: int,
    body: str,
    kind: GoalEventKind = "note",
    task_id: int | None = None,
) -> dict[str, Any]:
    with SessionLocal() as session:
        try:
            event = service.create_goal_event(
                session,
                goal_id,
                GoalEventCreate(kind=kind, body=body, task_id=task_id),
            )
        except ValueError as exc:
            return {"error": str(exc), "goal_id": goal_id, "task_id": task_id}
        if event is None:
            return {"error": "goal not found", "goal_id": goal_id}
        return goal_event_to_read(event).model_dump(mode="json")


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool_plain
    def create_goal(
        title: str,
        description: str | None = None,
        task_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Create a durable goal.

        Use goals for longer-lived outcomes or projects that need several
        concrete tasks over time. Keep the title outcome-shaped and the
        description concise Markdown. Optionally pass existing `task_ids`
        to link concrete next steps immediately.
        """
        return do_create_goal(title=title, description=description, task_ids=task_ids)

    @agent.tool_plain
    def list_goals(
        is_done: bool | None = None,
        title: str | None = None,
        offset: int = 0,
        limit: int = LIST_GOALS_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        """List goals, one page at a time.

        Use `is_done=False` for active goals and `is_done=True` for
        completed goals. `title` is a case-insensitive substring filter.
        Returns `{goals, total, offset, limit, has_more, next_offset}`.
        """
        return do_list_goals(is_done=is_done, title=title, offset=offset, limit=limit)

    @agent.tool_plain
    def get_goal(goal_id: int) -> dict[str, Any]:
        """Read full goal detail, including linked tasks and goal events."""
        return do_get_goal(goal_id)

    @agent.tool_plain
    def update_goal(
        goal_id: int,
        title: str | None = None,
        description: str | None = None,
        is_done: bool | None = None,
        clear_description: bool = False,
    ) -> dict[str, Any]:
        """Edit a goal.

        Pass only fields to change. `is_done=True` completes the goal;
        `is_done=False` reopens it. Pass `clear_description=True` to
        remove the description.
        """
        if clear_description and description is not None:
            return {"error": "pass either description or clear_description, not both"}
        return do_update_goal(
            goal_id,
            title=title if title is not None else _UNSET,
            description=None
            if clear_description
            else (description if description is not None else _UNSET),
            is_done=is_done if is_done is not None else _UNSET,
        )

    @agent.tool_plain
    def append_goal_event(
        goal_id: int,
        body: str,
        kind: GoalEventKind = "note",
        task_id: int | None = None,
    ) -> dict[str, Any]:
        """Append a concise event to a goal's log.

        Use this when the user reports progress, a linked task handoff
        changes the project picture, or you need to record why no next
        task was created. Prefer `update_goal` for durable description
        changes and completion.
        """
        return do_append_goal_event(goal_id=goal_id, body=body, kind=kind, task_id=task_id)
