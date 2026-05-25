"""Shared pagination helpers for agent tools.

A handful of read tools can dump enormous results in a single call —
every byte then lives in the agent's context until compaction. Clipping
would silently drop data the agent can't get back; pagination keeps the
data reachable and lets the agent pull only what it needs.

Two shapes of "too big", one envelope:

- too many items → `paginate(items, offset, limit)`
- one body too long → `window_text(text, offset, limit)`

Both return `has_more` + `next_offset` so the agent always has a
concrete way to fetch the rest (mirrors `read_file`'s offset/limit).
"""

from __future__ import annotations

from typing import Any, TypeVar

T = TypeVar("T")


def normalize_page(
    offset: int, limit: int, *, default_limit: int, max_limit: int
) -> tuple[int, int]:
    """Coerce caller-supplied paging args to sane values.

    These args are model-controlled, so they cannot be trusted to be
    reasonable: an accidental `limit=1_000_000` would defeat the whole
    point and flood context in one call. Negative offset → 0.
    Non-positive limit → `default_limit` (limit=0 almost certainly
    wants the default page, not an empty one). Anything above
    `max_limit` is clamped down to it — clamping not rejecting, so the
    call still succeeds and `has_more` tells the caller to page on.
    """
    safe_offset = max(0, offset)
    safe_limit = limit if limit and limit > 0 else default_limit
    safe_limit = min(safe_limit, max_limit)
    return safe_offset, safe_limit


def paginate(items: list[T], offset: int, limit: int) -> dict[str, Any]:
    """Slice `items` into a standard page envelope.

    `total` is the full count (so the agent knows how much it hasn't
    seen); `next_offset` is `None` when there is no further page.
    """
    total = len(items)
    page = items[offset : offset + limit]
    has_more = offset + limit < total
    return {
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
    }


def window_text(text: str, offset: int, limit: int) -> dict[str, Any]:
    """Return a `limit`-char window of `text` starting at `offset`.

    Companion to `paginate` for a single oversized body (a long chat
    message, a big knowledge entry). Concatenating successive windows
    reconstructs the original exactly — nothing is lost.
    """
    total_chars = len(text)
    chunk = text[offset : offset + limit]
    has_more = offset + limit < total_chars
    return {
        "text": chunk,
        "total_chars": total_chars,
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
    }
