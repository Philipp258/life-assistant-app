"""Pydantic AI tools for the knowledge store.

The agent navigates `data/knowledge/` like a code agent navigates a repo:
the system prompt carries a paths-and-titles tree of every entry, and the
agent opens individual files with `read_knowledge`.

Write tools (`save_knowledge`, `delete_knowledge`, `move_knowledge`, and
the folder trio) are explicit - the assistant only edits the store when the user
asks. The chip UX in chat surfaces every call so writes are never
invisible.

Logic lives in `app.knowledge.store`; this module only adapts the
agent-tool surface (parameter docs, error envelope) on top.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from app.agent.deps import AgentDeps
from app.agent.tools._paging import normalize_page, window_text
from app.knowledge import core as core_memory
from app.knowledge import store as fs

READ_KNOWLEDGE_PAGE_DEFAULT = 20_000
# A model-supplied `limit` above this is clamped down so one call can't
# flood context with a huge single entry regardless of the arg.
READ_KNOWLEDGE_PAGE_MAX = 50_000


def _err(exc: Exception) -> dict[str, Any]:
    return {"error": str(exc)}


def _ok_knowledge(item: fs.Knowledge) -> dict[str, Any]:
    return {
        "ok": True,
        "path": item.path,
        "title": item.title,
        "id": item.id,
        "created": item.created,
        "updated": item.updated,
    }


def do_read_knowledge(
    path: str,
    offset: int = 0,
    limit: int = READ_KNOWLEDGE_PAGE_DEFAULT,
) -> dict[str, Any]:
    try:
        item = fs.read_knowledge(path)
    except fs.KnowledgeError as exc:
        return _err(exc)
    safe_offset, safe_limit = normalize_page(
        offset,
        limit,
        default_limit=READ_KNOWLEDGE_PAGE_DEFAULT,
        max_limit=READ_KNOWLEDGE_PAGE_MAX,
    )
    win = window_text(item.body, safe_offset, safe_limit)
    return {
        "path": item.path,
        "title": item.title,
        "id": item.id,
        "created": item.created,
        "updated": item.updated,
        "body": win["text"],
        "total_chars": win["total_chars"],
        "offset": win["offset"],
        "limit": win["limit"],
        "has_more": win["has_more"],
        "next_offset": win["next_offset"],
    }


def do_save_knowledge(path: str, body: str, title: str | None = None) -> dict[str, Any]:
    try:
        item = fs.save_knowledge(path, body, title=title)
    except fs.KnowledgeError as exc:
        return _err(exc)
    return _ok_knowledge(item)


def do_delete_knowledge(path: str) -> dict[str, Any]:
    try:
        fs.delete_knowledge(path)
    except fs.KnowledgeError as exc:
        return _err(exc)
    return {"ok": True, "path": path}


def do_move_knowledge(src: str, dst: str) -> dict[str, Any]:
    try:
        item = fs.move_knowledge(src, dst)
    except fs.KnowledgeError as exc:
        return _err(exc)
    return _ok_knowledge(item)


def do_create_folder(path: str) -> dict[str, Any]:
    try:
        out = fs.create_folder(path)
    except fs.KnowledgeError as exc:
        return _err(exc)
    return {"ok": True, "path": out}


def do_rename_folder(src: str, dst: str) -> dict[str, Any]:
    try:
        out = fs.rename_folder(src, dst)
    except fs.KnowledgeError as exc:
        return _err(exc)
    return {"ok": True, "path": out}


def do_delete_folder(path: str) -> dict[str, Any]:
    try:
        fs.delete_folder(path)
    except fs.KnowledgeError as exc:
        return _err(exc)
    return {"ok": True, "path": path}


def do_save_core_memory(name: str, body: str) -> dict[str, Any]:
    if name not in core_memory.CORE_FILES:
        return {
            "error": f"unknown core memory file {name!r}; expected one of "
            f"{', '.join(core_memory.CORE_FILES)}"
        }
    core_memory.write(name, body)
    return {"ok": True, "name": name}


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool_plain
    def read_knowledge(
        path: str,
        offset: int = 0,
        limit: int = READ_KNOWLEDGE_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        """Read a knowledge entry by relative path.

        `path` is relative to data/knowledge/ — e.g. `interests/bikes.md`.
        Returns frontmatter (id, title, created, updated) plus a
        `limit`-char window of the body starting at `offset` (default
        20000 chars from the top, 50000 max — a larger `limit` is
        clamped). Large entries page: `{total_chars,
        has_more, next_offset}` tell you whether there's more and where
        to continue — pass `next_offset` as `offset`. Concatenating
        successive windows reconstructs the entry exactly.
        """
        return do_read_knowledge(path, offset=offset, limit=limit)

    @agent.tool_plain
    def save_knowledge(path: str, body: str, title: str | None = None) -> dict[str, Any]:
        """Create or update a knowledge entry.

        `path` is relative to data/knowledge/ and must end in `.md`.
        Parent folders are auto-created. Frontmatter (id, created, title,
        updated) is managed for you — `id`/`created` are set on first
        save and preserved; `updated` bumps every time. Pass `body` as
        the markdown content *without* frontmatter — just the body.

        Use this when the user says things like "remember that…",
        "make a note that…", or asks you to record something. Pick a
        path under a sensible folder (e.g. `interests/`, `people/`,
        `projects/`); create the folder implicitly by including it in
        the path.
        """
        return do_save_knowledge(path, body, title=title)

    @agent.tool_plain
    def delete_knowledge(path: str) -> dict[str, Any]:
        """Delete a knowledge entry. No undo — only call when explicitly asked."""
        return do_delete_knowledge(path)

    @agent.tool_plain
    def move_knowledge(src: str, dst: str) -> dict[str, Any]:
        """Move/rename an entry. Both paths are relative to data/knowledge/."""
        return do_move_knowledge(src, dst)

    @agent.tool_plain
    def create_folder(path: str) -> dict[str, Any]:
        """Create a folder under data/knowledge/.

        Folders are auto-created by `save_knowledge` too — use this only
        when you want an empty folder ahead of time.
        """
        return do_create_folder(path)

    @agent.tool_plain
    def rename_folder(src: str, dst: str) -> dict[str, Any]:
        """Rename or move a folder. Both paths are relative to data/knowledge/."""
        return do_rename_folder(src, dst)

    @agent.tool_plain
    def delete_folder(path: str) -> dict[str, Any]:
        """Delete a folder and every entry under it. Hard delete — no undo."""
        return do_delete_folder(path)

    @agent.tool_plain
    def save_core_memory(name: str, body: str) -> dict[str, Any]:
        """Rewrite a core-memory file. Only call after the user has agreed
        in chat — this overwrites the file unconditionally.

        `name` must be `'about_user'` (facts about the user) or
        `'behavior'` (how the assistant should write/act). Both are loaded verbatim
        into your system prompt every turn, so keep them tight: long
        context costs tokens on every message.

        `body` is the *full new content* of the file, including any
        existing material you want to keep. There is no diff/patch input.
        """
        return do_save_core_memory(name, body)
