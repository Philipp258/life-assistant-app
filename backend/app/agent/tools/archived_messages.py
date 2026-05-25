"""Pydantic AI tool for searching older main-chat history.

Two mechanisms hide main-chat messages from the agent's working context
but keep the originals in the DB:

- `archived_at` is stamped by `/new`. The user reset the chat — both the
  UI and the agent's live history loader skip these rows.
- `compacted_at` is stamped by main-chat compaction. The summary message
  takes their place in the agent's context, but the originals stay in
  the DB and the user can still see them in the UI.

`search_main_chat_history` lets the agent look back through that older
history on demand — to reflect on past conversations, find a thread the
user mentioned in passing, or scan for context that a compaction summary
elided. Hardcoded to the singleton main session; task chats don't `/new`
and aren't compacted, so the tool always reads main. Available in both
main and task chats: from main chat the agent reaches further back than
its in-prompt context, and from a task chat the agent can pull older
main-chat context that isn't in the recent tail returned by
`read_main_chat_recent`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic_ai import Agent
from sqlalchemy import or_, select

from app.agent.deps import AgentDeps
from app.agent.tools.chats import flatten_parts, role_for
from app.chat.models import Message
from app.chat.service import get_or_create_main_session, parse_message
from app.datetime_utils import normalize_to_naive_utc, serialize_utc
from app.db import SessionLocal


def _archive_reason(row: Message) -> str:
    """Why this row is hidden from live context. `archived_at` wins when
    both are set — `/new` is the more recent and more user-visible event."""
    if row.archived_at is not None:
        return "archived"
    return "compacted"


def _render_row(row: Message) -> dict[str, Any]:
    msg = parse_message(row)
    return {
        "id": row.id,
        "kind": row.kind,
        "role": role_for(msg) if msg is not None else "user",
        "text": flatten_parts(msg) if msg is not None else "",
        "created_at": serialize_utc(row.created_at),
        "archived_via": _archive_reason(row),
        "archived_at": serialize_utc(row.archived_at),
        "compacted_at": serialize_utc(row.compacted_at),
    }


def do_read_archived_messages(
    *,
    query: str | None = None,
    context: int = 2,
    offset: int = 0,
    limit: int = 10,
    before: datetime | None = None,
    after: datetime | None = None,
) -> dict[str, Any]:
    """Page through main-chat archived/compacted messages with grep-style context.

    With `query`, returns matching rows each wrapped in `context` archive
    rows before and after — so the agent can read the conversation
    around each hit. Without `query`, walks the archive flat. Either
    way, paginate via `offset` / `limit`; the response carries `total`
    and `has_more` so callers can step through.
    """
    if limit <= 0:
        return {"error": "limit must be positive", "limit": limit}
    if offset < 0:
        return {"error": "offset must be non-negative", "offset": offset}
    if context < 0:
        return {"error": "context must be non-negative", "context": context}

    needle = query.lower() if query else None

    with SessionLocal() as session:
        main_session_id = get_or_create_main_session(session).id
        stmt = (
            select(Message)
            .where(
                Message.session_id == main_session_id,
                or_(
                    Message.archived_at.is_not(None),
                    Message.compacted_at.is_not(None),
                ),
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        before_naive = normalize_to_naive_utc(before)
        after_naive = normalize_to_naive_utc(after)
        if before_naive is not None:
            stmt = stmt.where(Message.created_at <= before_naive)
        if after_naive is not None:
            stmt = stmt.where(Message.created_at >= after_naive)
        rows = session.scalars(stmt).all()

    rendered = [_render_row(row) for row in rows]

    if needle is None:
        total = len(rendered)
        page = rendered[offset : offset + limit]
        matches: list[dict[str, Any]] = [{"before": [], "match": m, "after": []} for m in page]
    else:
        hit_idxs = [i for i, r in enumerate(rendered) if needle in r["text"].lower()]
        total = len(hit_idxs)
        page_idxs = hit_idxs[offset : offset + limit]
        matches = [
            {
                "before": rendered[max(0, i - context) : i],
                "match": rendered[i],
                "after": rendered[i + 1 : i + 1 + context],
            }
            for i in page_idxs
        ]

    return {
        "matches": matches,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool_plain
    def search_main_chat_history(
        query: str | None = None,
        context: int = 2,
        offset: int = 0,
        limit: int = 10,
        before: datetime | None = None,
        after: datetime | None = None,
    ) -> dict[str, Any]:
        """Search older main-chat history that isn't in your live context.

        Two reasons a main-chat row would be hidden from live context:
        the user reset the chat with `/new` (`archived_via='archived'`),
        or older history got rolled into a `<conversation_summary>`
        block by main-chat compaction (`archived_via='compacted'`).
        Either way, the originals stay in the DB and this tool surfaces
        them — useful whenever you want to look back, e.g. to reflect on
        past conversations or pull up something the user mentioned ages
        ago. From main chat, this is how you reach further back than the
        recent context already in your prompt. From a task chat, this
        complements `read_main_chat_recent` (which only shows the recent
        visible tail) when you need older context.

        Always reads the main chat's archive. Use `list_chat_messages`
        for cross-session reads (e.g. a task chat looked up via
        `get_task`).

        - `query`: case-insensitive substring match on the rendered
          message text — pick a distinctive word or phrase. Without it,
          you flat-walk the archive in chronological order.
        - `context`: with `query`, how many archived rows to include
          before and after each hit so you can read the conversation
          around it (default 2, grep-style). Ignored without `query`.
        - `offset` / `limit`: paginate through results. `limit` is
          matches per page (default 10); set `offset = previous_offset +
          limit` to step forward, decrease to step back.
        - `before` / `after`: inclusive bounds on each row's original
          `created_at`. Narrow when you know roughly when something
          happened.

        Returns `{matches, total, offset, limit, has_more}`. Each match
        is `{before: [...], match: {...}, after: [...]}` where each row
        has `{id, kind, role, text, created_at, archived_via,
        archived_at, compacted_at}`. `total` counts hits (or all
        archived rows if no `query`); `has_more = offset + limit < total`.
        """
        return do_read_archived_messages(
            query=query,
            context=context,
            offset=offset,
            limit=limit,
            before=before,
            after=after,
        )
