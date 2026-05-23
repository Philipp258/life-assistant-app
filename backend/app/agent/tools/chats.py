"""Pydantic AI tools for reading chat sessions and asking the user.

`list_chat_messages` lets the agent read the message history of any
session — needed by the weekly reflection so it can actually inspect
what happened, not just look at task titles.

`ask_user_choice` posts a structured question with picklist options into
the current task chat and reassigns the task to the user. It is recorded
as a normal tool call (no new message kind), so it round-trips through
the existing `parts_json` storage. The frontend renders it as a card
with reply buttons; the user's pick comes back as a normal user message
on the next turn.

`read_main_chat_recent` lets task agents inspect the user's primary chat
when needed. Task agents do not post to main chat directly; terminal
task tools record a hidden handoff that the main session later drains as
a task-terminal event (`app.chat.events`) and acts on conversationally.

Pure logic lives in plain `do_*` functions so unit tests can exercise
them without a live model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic_ai import Agent, RunContext
from sqlalchemy import func, select

from app.agent.deps import AgentDeps
from app.agent.tools._paging import normalize_page
from app.agent.tools._task_scope import current_task_id, only_in_task_chat
from app.chat.models import ChatSession, Message
from app.datetime_utils import normalize_to_naive_utc, serialize_utc
from app.db import SessionLocal
from app.tasks import service as tasks_service
from app.tasks.schemas import TaskUpdate


_TOOL_RETURN_PREVIEW_CHARS = 200


def flatten_parts(parts: list[dict[str, Any]]) -> str:
    """Render pydantic-ai message parts as a single readable text blob.

    Tool calls/returns are shown as one-liners so the agent can see *that*
    a tool ran without drowning in JSON. Tool returns are truncated.
    """
    chunks: list[str] = []
    for part in parts:
        kind = part.get("part_kind")
        if kind in ("text", "user-prompt"):
            content = part.get("content")
            if content:
                chunks.append(str(content))
        elif kind == "tool-call":
            name = part.get("tool_name", "?")
            args = part.get("args", "")
            # Keep this deliberately non-XML/non-control-looking. These
            # transcript strings are context for the agent, and may be
            # summarized or quoted in a later user-facing answer. A prior
            # angle-bracket form (`<tool_call: update_task(...)>`) leaked
            # verbatim into main chat and looked like executable internal
            # syntax. Use plain prose so accidental copying is harmless.
            chunks.append(f"Internal tool call recorded: {name}; args: {args}")
        elif kind == "tool-return":
            name = part.get("tool_name", "?")
            content = part.get("content", "")
            text = str(content)
            if len(text) > _TOOL_RETURN_PREVIEW_CHARS:
                text = text[:_TOOL_RETURN_PREVIEW_CHARS] + "…"
            chunks.append(f"Internal tool result recorded: {name}; preview: {text}")
        elif kind == "retry-prompt":
            content = part.get("content", "")
            chunks.append(f"Internal retry prompt recorded: {content}")
        # system-prompt parts are skipped on purpose — irrelevant for
        # cross-session reading and noisy.
    return "\n".join(c for c in chunks if c)


def role_for(kind: str, parts: list[dict[str, Any]]) -> str:
    if kind == "request":
        for p in parts:
            if p.get("part_kind") == "user-prompt":
                return "user"
            if p.get("part_kind") == "tool-return":
                return "tool"
        return "user"
    return "assistant"


LIST_MESSAGES_PAGE_DEFAULT = 50
# A model-supplied `limit` above this is clamped down so one call can't
# flood context regardless of the arg.
LIST_MESSAGES_PAGE_MAX = 200


def do_list_chat_messages(
    session_id: int,
    since: datetime | None = None,
    limit: int = LIST_MESSAGES_PAGE_DEFAULT,
    offset: int = 0,
) -> dict[str, Any]:
    """Page through a session's messages, oldest first.

    `total` counts every message matching the filter (so the agent
    knows how much it hasn't read); `offset`/`limit` slice in SQL so a
    long history never loads in full.
    """
    safe_offset, safe_limit = normalize_page(
        offset,
        limit,
        default_limit=LIST_MESSAGES_PAGE_DEFAULT,
        max_limit=LIST_MESSAGES_PAGE_MAX,
    )
    with SessionLocal() as session:
        chat = session.get(ChatSession, session_id)
        if chat is None:
            return {"error": "session not found", "session_id": session_id}
        base = select(Message).where(Message.session_id == session_id)
        since_naive = normalize_to_naive_utc(since)
        if since_naive is not None:
            base = base.where(Message.created_at >= since_naive)
        total = session.scalar(select(func.count()).select_from(base.subquery()))
        rows = session.scalars(
            base.order_by(Message.created_at.asc(), Message.id.asc())
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()

    items: list[dict[str, Any]] = []
    for row in rows:
        raw: dict[str, Any] = row.parts_json if isinstance(row.parts_json, dict) else {}
        parts = raw.get("parts", []) or []
        items.append(
            {
                "id": row.id,
                "kind": row.kind,
                "role": role_for(row.kind, parts),
                "text": flatten_parts(parts),
                "created_at": serialize_utc(row.created_at),
            }
        )
    total = total or 0
    has_more = safe_offset + safe_limit < total
    return {
        "messages": items,
        "total": total,
        "offset": safe_offset,
        "limit": safe_limit,
        "has_more": has_more,
        "next_offset": safe_offset + safe_limit if has_more else None,
    }


def do_ask_user_choice(
    task_id: int,
    question: str,
    options: list[str],
    allow_free_text: bool = True,
) -> dict[str, Any]:
    """Reassign the task to the user. The frontend renders the question
    + options from the recorded tool call. Pure side-effect on the task;
    the choice itself is captured by the agent's tool-call args.
    """
    if not options or len(options) < 2:
        return {"error": "ask_user_choice needs at least 2 options"}
    if len(options) > 6:
        return {"error": "ask_user_choice supports at most 6 options"}
    with SessionLocal() as session:
        task = tasks_service.update_task(session, task_id, TaskUpdate(assignee="user"))
        if task is None:
            return {"error": "task not found", "task_id": task_id}
        from app.chat.service import save_task_handoff

        options_text = "\n".join(f"- {option}" for option in options)
        save_task_handoff(
            session,
            task.chat_session_id,
            (
                "The task is waiting for the user to choose an option.\n\n"
                f"Question: {question.strip()}\n\n"
                f"Options:\n{options_text}\n\n"
                f"Free-text answer allowed: {'yes' if allow_free_text else 'no'}"
            ),
        )
    return {
        "ok": True,
        "asked": question,
        "options": options,
        "allow_free_text": allow_free_text,
    }


def do_read_main_chat_recent(limit: int = 20) -> list[dict[str, Any]]:
    """Latest N visible main-chat messages, oldest first.

    Resolves the singleton main session itself so the agent never has to
    know the id. Excludes rows hidden by `/new` (`archived_at IS NOT
    NULL`) so the tail mirrors what the user actually sees in main chat
    right now. Older archived/compacted history is reachable via
    `search_main_chat_history` instead. Returns a compact role / text /
    created_at triple per message.
    """
    from app.chat.service import get_or_create_main_session

    with SessionLocal() as session:
        main = get_or_create_main_session(session)
        main_id = main.id
        stmt = (
            select(Message)
            .where(
                Message.session_id == main_id,
                Message.archived_at.is_(None),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        rows = list(session.scalars(stmt).all())

    rows.reverse()  # latest N, returned oldest-first
    out: list[dict[str, Any]] = []
    for row in rows:
        raw: dict[str, Any] = row.parts_json if isinstance(row.parts_json, dict) else {}
        parts = raw.get("parts", []) or []
        out.append(
            {
                "role": role_for(row.kind, parts),
                "text": flatten_parts(parts),
                "created_at": serialize_utc(row.created_at),
            }
        )
    return out


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool_plain
    def list_chat_messages(
        session_id: int,
        since: datetime | None = None,
        limit: int = LIST_MESSAGES_PAGE_DEFAULT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Read messages from any chat session, oldest first, paged.

        Returns `{messages, total, offset, limit, has_more,
        next_offset}` where each message is `{id, kind, role, text,
        created_at}`. Tool calls/returns are rendered as one-line
        summaries — enough to see what happened without flooding the
        context. Use this to read what went on in a task's chat (look
        up `chat_session_id` via `get_task`), or to revisit a prior
        conversation.

        - `since`: only messages at or after this timestamp.
        - `limit` / `offset`: page through history (default 50 per
          page, 200 max — a larger `limit` is clamped). `total` is the
          full match count; page forward by passing the returned
          `next_offset` as `offset`.
        """
        return do_list_chat_messages(session_id=session_id, since=since, limit=limit, offset=offset)

    @agent.tool_plain(prepare=only_in_task_chat)
    def read_main_chat_recent(limit: int = 20) -> list[dict[str, Any]]:
        """Peek the recent visible tail of the user's main chat.

        Use when the task needs main-chat context — check what the user
        already knows, what they just asked about, and whether your task
        context has changed. The main chat is their primary conversation
        with you; it is NOT a task activity feed.

        Returns up to `limit` latest messages currently visible in main
        chat (default 20), oldest first, each with `{role, text,
        created_at}`. Rows hidden by `/new` are excluded — this is just
        the recent visible tail for notification context, not the full
        archive. For older archived or compacted history, use
        `search_main_chat_history` instead. Only available inside a task
        chat; the main chat agent already sees its own recent context.
        """
        return do_read_main_chat_recent(limit=limit)

    @agent.tool(prepare=only_in_task_chat)
    def ask_user_choice(
        ctx: RunContext[AgentDeps],
        question: str,
        options: list[str],
        allow_free_text: bool = True,
    ) -> dict[str, Any]:
        """Ask the user to pick from a small set of options.

        Use this when you want input that's better expressed as a choice
        than as open-ended text — e.g. "save this as a hard rule, a
        gentle preference, or skip?". Provide 2-6 short option strings.
        If `allow_free_text` is True (default), the user can also reply
        with their own wording.

        Side-effect: this reassigns the task to the user, so the
        autonomous loop pauses. The user's pick comes back as a normal
        user message on the next turn — your follow-up runs as one
        agent turn in response to that message. Only available inside
        a task chat.
        """
        tid = current_task_id(ctx)
        if tid is None:
            return {"error": "ask_user_choice is only available inside a task chat"}
        return do_ask_user_choice(
            task_id=tid,
            question=question,
            options=options,
            allow_free_text=allow_free_text,
        )
