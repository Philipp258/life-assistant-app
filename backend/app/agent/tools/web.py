"""Web tools for the agent — fetch + Brave-backed search."""

from __future__ import annotations

import re
from typing import Any

import httpx
from pydantic_ai import Agent
from sqlalchemy.orm import Session

from app.agent.deps import AgentDeps
from app.agent.tools._paging import normalize_page, window_text
from app.agent.tools._task_scope import only_in_task_chat
from app.db import SessionLocal
from app.settings import service as settings_service

MAX_BODY_CHARS = 30_000
DEFAULT_TIMEOUT = 30.0
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
SEARCH_DEFAULT_COUNT = 10
SEARCH_MAX_COUNT = 20

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _strip_html(html: str) -> str:
    text = _SCRIPT_STYLE_RE.sub("", html)
    text = _TAG_RE.sub("", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def do_web_fetch(url: str, offset: int = 0, limit: int = MAX_BODY_CHARS) -> dict[str, Any]:
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=DEFAULT_TIMEOUT)
    except httpx.HTTPError as exc:
        return {"error": str(exc)}

    content_type = resp.headers.get("content-type", "")
    body = resp.text
    if "html" in content_type.lower():
        body = _strip_html(body)

    # Window the body instead of silently dropping the tail: a long page is
    # reachable in full by paging on `next_offset`, like read_file/read_knowledge.
    safe_offset, safe_limit = normalize_page(
        offset, limit, default_limit=MAX_BODY_CHARS, max_limit=MAX_BODY_CHARS
    )
    win = window_text(body, safe_offset, safe_limit)
    return {
        "url": str(resp.url),
        "status": resp.status_code,
        "content_type": content_type,
        "body": win["text"],
        "total_chars": win["total_chars"],
        "offset": win["offset"],
        "limit": win["limit"],
        "has_more": win["has_more"],
        "next_offset": win["next_offset"],
        # Back-compat alias for callers that only checked whether the body was clipped.
        "truncated": win["has_more"],
    }


def _get_brave_api_key(db: Session | None = None) -> str | None:
    if db is not None:
        return settings_service.get_brave_api_key(db)
    with SessionLocal() as owned_db:
        return settings_service.get_brave_api_key(owned_db)


def do_web_search(
    query: str,
    count: int = SEARCH_DEFAULT_COUNT,
    db: Session | None = None,
) -> dict[str, Any]:
    brave_api_key = _get_brave_api_key(db)
    if not brave_api_key:
        return {"error": "Brave API key not configured"}
    count = max(1, min(count, SEARCH_MAX_COUNT))
    try:
        resp = httpx.get(
            BRAVE_ENDPOINT,
            params={"q": query, "count": count},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": brave_api_key,
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return {"error": str(exc)}

    if resp.status_code != 200:
        return {
            "error": f"brave returned {resp.status_code}",
            "body": resp.text[:1000],
        }

    try:
        data = resp.json()
    except ValueError as exc:
        return {"error": f"non-json response: {exc}"}

    web_section = data.get("web") or {}
    raw = web_section.get("results") or []
    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("description", ""),
        }
        for r in raw[:count]
    ]
    return {
        "query": query,
        "results": results,
        "count": len(results),
    }


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool_plain(prepare=only_in_task_chat)
    def web_fetch(url: str, offset: int = 0, limit: int = MAX_BODY_CHARS) -> dict[str, Any]:
        """Fetch a URL. HTML is stripped to text.

        Follows redirects. No JS render, no auth, no cookies. Returns a
        `limit`-char window of the body starting at `offset` (default
        30000 chars from the top, 30000 max). Response is `{url, status,
        content_type, body, total_chars, offset, limit, has_more,
        next_offset, truncated}`. Page forward by passing `next_offset`
        as `offset` to read a long page. Non-2xx responses come back with
        their status — not raised.
        """
        return do_web_fetch(url, offset=offset, limit=limit)

    @agent.tool_plain(prepare=only_in_task_chat)
    def web_search(query: str, count: int = SEARCH_DEFAULT_COUNT) -> dict[str, Any]:
        """Search the web via Brave. Returns top results.

        `count` is clamped to 1..20 (default 10). Returns
        `{query, results: [{title, url, snippet}], count}`. Use
        `web_fetch` on a result URL to read the full page. Returns
        `{error: ...}` if the Brave API key is not configured in the
        runtime settings or Brave fails.
        """
        return do_web_search(query, count=count)
