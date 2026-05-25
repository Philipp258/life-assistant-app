"""Raw filesystem tools for the agent — openclaw-style.

Read/write/edit/glob/grep with paths resolved against `REPO_ROOT`
when relative. No sandbox; absolute paths reach the real fs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from app.agent.deps import AgentDeps
from app.agent.tools._paging import normalize_page, paginate
from app.agent.tools._task_scope import only_in_task_chat
from app.config import DEFAULTS_SKILLS_DIR, REPO_ROOT

MAX_LINE_CHARS = 2000
DEFAULT_READ_LIMIT = 2000
GLOB_CAP = 200
# Hard ceiling on matches collected before paging — bounds memory/work
# on a pathologically broad pattern. The agent narrows the pattern if it
# hits this; `total` in the envelope tells it the scan was capped.
GREP_SCAN_CEILING = 1000
GREP_PAGE_DEFAULT = 100
# Upper bound on a single page — a model-supplied `limit` above this is
# clamped down so one call can't flood context regardless of the arg.
GREP_PAGE_MAX = 500
GREP_TIMEOUT_SECONDS = 30
BINARY_SNIFF_BYTES = 8192


def _err(exc: Exception) -> dict[str, Any]:
    return {"error": str(exc)}


def _resolve(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p


def _is_default_skill(target: Path) -> bool:
    """True if target lives under DEFAULTS_SKILLS_DIR.

    Default skills are immutable. Block writes/edits at the tool layer
    so the agent gets a clear error instead of silently shadowing the
    default with a user copy.
    """
    try:
        resolved = target.resolve(strict=False)
        defaults = DEFAULTS_SKILLS_DIR.resolve(strict=False)
    except OSError:
        return False
    return resolved == defaults or defaults in resolved.parents


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data


def do_read_file(path: str, offset: int = 0, limit: int = DEFAULT_READ_LIMIT) -> dict[str, Any]:
    target = _resolve(path)
    try:
        if not target.exists():
            return _err(FileNotFoundError(f"{path}: not found"))
        if target.is_dir():
            return _err(IsADirectoryError(f"{path}: is a directory"))
        with target.open("rb") as fh:
            head = fh.read(BINARY_SNIFF_BYTES)
        if _looks_binary(head):
            return _err(ValueError(f"{path}: binary file (refused)"))
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _err(exc)

    raw_lines = text.splitlines()
    total = len(raw_lines)
    start = max(offset, 0)
    end = start + limit if limit > 0 else total
    chunk = raw_lines[start:end]

    rendered: list[str] = []
    for i, line in enumerate(chunk, start=start + 1):
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + "...(truncated)"
        rendered.append(f"{i:>6}\t{line}")

    return {
        "path": str(target),
        "lines": "\n".join(rendered),
        "total_lines": total,
        "truncated": end < total,
    }


def do_write_file(path: str, content: str) -> dict[str, Any]:
    target = _resolve(path)
    if _is_default_skill(target):
        return _err(
            PermissionError(
                "default skills are read-only; install a custom skill "
                "with a different name under data/skills/ instead"
            )
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        return _err(exc)
    return {"ok": True, "path": str(target), "bytes": len(content.encode("utf-8"))}


def do_edit_file(
    path: str, old_string: str, new_string: str, replace_all: bool = False
) -> dict[str, Any]:
    target = _resolve(path)
    if _is_default_skill(target):
        return _err(
            PermissionError(
                "default skills are read-only; install a custom skill "
                "with a different name under data/skills/ instead"
            )
        )
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return _err(exc)

    count = text.count(old_string)
    if count == 0:
        return _err(ValueError("old_string not found"))
    if count > 1 and not replace_all:
        return _err(
            ValueError(
                f"old_string matches {count} times; pass replace_all=True or "
                "expand the snippet to be unique"
            )
        )

    new_text = (
        text.replace(old_string, new_string)
        if replace_all
        else text.replace(old_string, new_string, 1)
    )
    try:
        target.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        return _err(exc)
    return {"ok": True, "path": str(target), "replacements": count if replace_all else 1}


def do_glob_files(pattern: str) -> dict[str, Any]:
    if Path(pattern).is_absolute():
        return _err(
            ValueError(
                f"glob pattern must be relative to repo root, got absolute path {pattern!r}; "
                "use e.g. 'backend/**/*.py' instead of '/abs/path/**/*.py'"
            )
        )
    try:
        matches = list(REPO_ROOT.glob(pattern))
        if not matches:
            matches = list(REPO_ROOT.rglob(pattern))
    except (OSError, NotImplementedError, ValueError) as exc:
        return _err(exc)
    matches = [p for p in matches if p.is_file()]
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    truncated = len(matches) > GLOB_CAP
    matches = matches[:GLOB_CAP]
    return {
        "matches": [str(p) for p in matches],
        "truncated": truncated,
    }


def _grep_with_rg(
    pattern: str, path: str, glob: str | None
) -> list[dict[str, Any]] | dict[str, Any] | None:
    """Collect matches via `rg`. Returns the match list, an error
    envelope, or None when `rg` is unavailable (caller falls back)."""
    if shutil.which("rg") is None:
        return None
    cmd = ["rg", "--color=never", "-n", "--no-heading", "-S"]
    if glob:
        cmd += ["-g", glob]
    cmd += [pattern, path]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError as exc:
        return _err(exc)

    matches: list[dict[str, Any]] = []
    deadline = time.monotonic() + GREP_TIMEOUT_SECONDS
    try:
        assert proc.stdout is not None
        # Stream line-by-line. A broad pattern produces matches fast, so
        # we hit the ceiling and stop reading almost immediately instead
        # of buffering the whole (potentially huge) rg output. The
        # per-line deadline bounds the streaming case; the `finally`
        # below kills rg so it doesn't keep scanning the tree after we
        # stop reading.
        for line in proc.stdout:
            if time.monotonic() > deadline:
                break
            # rg format: path:line:text
            parts = line.rstrip("\n").split(":", 2)
            if len(parts) < 3:
                continue
            try:
                ln = int(parts[1])
            except ValueError:
                continue
            matches.append({"path": parts[0], "line": ln, "text": parts[2]})
            if len(matches) >= GREP_SCAN_CEILING:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    return matches


def _grep_python(
    pattern: str, path: str, glob: str | None
) -> list[dict[str, Any]] | dict[str, Any]:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return _err(exc)

    root = _resolve(path)
    if not root.exists():
        return _err(FileNotFoundError(f"{path}: not found"))

    files: list[Path]
    if root.is_file():
        files = [root]
    else:
        glob_pattern = glob or "**/*"
        files = [p for p in root.glob(glob_pattern) if p.is_file()]

    matches: list[dict[str, Any]] = []
    for fp in files:
        try:
            with fp.open("rb") as fh:
                head = fh.read(BINARY_SNIFF_BYTES)
            if _looks_binary(head):
                continue
            with fp.open("r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, start=1):
                    if regex.search(line):
                        matches.append(
                            {
                                "path": str(fp),
                                "line": i,
                                "text": line.rstrip("\n"),
                            }
                        )
                        if len(matches) >= GREP_SCAN_CEILING:
                            return matches
        except OSError:
            continue
    return matches


def do_grep(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    offset: int = 0,
    limit: int = GREP_PAGE_DEFAULT,
) -> dict[str, Any]:
    """Search file contents, returning one page of matches.

    Matches are collected (up to `GREP_SCAN_CEILING`) then paged via the
    shared envelope so a broad pattern can't flood context — the agent
    pages with `offset` instead of losing matches to a silent cap.

    Residual lossy edge: a pattern matching more than the ceiling can't
    have its tail paged (the scan stopped — rg is streamed and killed
    once the ceiling is hit, so it never buffers the whole output).
    `scan_capped=True` flags this so the caller narrows rather than
    trusting `total`. `limit` above `GREP_PAGE_MAX` is clamped down.
    """
    result = _grep_with_rg(pattern, path, glob)
    if result is None:
        result = _grep_python(pattern, path, glob)
    if isinstance(result, dict):  # error envelope
        return result
    safe_offset, safe_limit = normalize_page(
        offset, limit, default_limit=GREP_PAGE_DEFAULT, max_limit=GREP_PAGE_MAX
    )
    page = paginate(result, safe_offset, safe_limit)
    page["matches"] = page.pop("items")
    page["scan_capped"] = len(result) >= GREP_SCAN_CEILING
    return page


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool_plain
    def read_file(path: str, offset: int = 0, limit: int = DEFAULT_READ_LIMIT) -> dict[str, Any]:
        """Read a text file. Path is relative to repo root or absolute.

        Returns `cat -n` formatted lines starting at 1-indexed
        `offset` (default 0 = from the top), up to `limit` lines.
        Individual lines >2000 chars get truncated. Binary files are
        refused. `total_lines` is the file's full line count.
        """
        return do_read_file(path, offset=offset, limit=limit)

    @agent.tool_plain(prepare=only_in_task_chat)
    def write_file(path: str, content: str) -> dict[str, Any]:
        """Overwrite a file. Auto-creates parent dirs. No undo.

        Path resolves against repo root. For knowledge entries use
        `save_knowledge` (manages frontmatter, renders as a card).
        For core memory use `save_core_memory` (validates the target).
        """
        return do_write_file(path, content)

    @agent.tool_plain(prepare=only_in_task_chat)
    def edit_file(
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> dict[str, Any]:
        """Exact-string replacement in a file.

        `old_string` must match exactly (no fuzz). Errors if not
        found, or if it matches more than once and `replace_all=False`.
        Pass enough surrounding context for `old_string` to be unique
        in the file.
        """
        return do_edit_file(path, old_string, new_string, replace_all=replace_all)

    @agent.tool_plain
    def glob_files(pattern: str) -> dict[str, Any]:
        """Find files by glob pattern, sorted by mtime (newest first).

        Pattern is evaluated relative to repo root (e.g.
        `backend/**/*.py`). Absolute patterns like `/etc/**/*.conf`
        are rejected — use `bash` if you need to search outside the
        repo. Capped at 200 results.
        """
        return do_glob_files(pattern)

    @agent.tool_plain
    def grep(
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        offset: int = 0,
        limit: int = GREP_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        """Search file contents for a regex, one page at a time.

        Uses `rg` if available, falls back to a Python regex walk.
        `path` is relative to repo root (default = repo root). `glob`
        filters which files to search (e.g. `*.py`).

        Returns `{matches: [{path, line, text}], total, offset, limit,
        has_more, next_offset, scan_capped}`. Page forward by passing
        `next_offset` as `offset`. Default page is 100 matches; `limit`
        is clamped to 500 max (a bigger value just pages, it does not
        return more in one call).

        `total` is the full match count and paging reaches all of it —
        UNLESS `scan_capped` is true, meaning the pattern matched more
        than the 1000 scanned: then `total` is only a lower bound
        (== 1000), the real count is unknown, and matches beyond 1000
        are NOT reachable by paging. Narrow the pattern in that case;
        do not trust `total` or assume you've seen everything.
        """
        return do_grep(pattern, path=path, glob=glob, offset=offset, limit=limit)
