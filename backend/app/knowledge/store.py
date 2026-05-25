"""Knowledge store: file-on-disk operations under `data/knowledge/`.

Knowledge entries are markdown files with YAML-ish frontmatter (id, title,
created, updated). Used by the agent tools (`read_knowledge`,
`save_knowledge`, …) and by the REST router behind the Knowledge screen.

Path-traversal hardening: every public function takes a *relative* path
(string, forward-slash) and resolves it strictly under KNOWLEDGE_DIR.
Symlinks pointing outside are rejected.
"""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import KNOWLEDGE_DIR


class KnowledgeError(Exception):
    """Raised on bad paths, missing files, or destination conflicts."""


@dataclass
class Knowledge:
    path: str  # relative to KNOWLEDGE_DIR, forward-slash, e.g. "interests/bikes.md"
    id: str
    title: str
    created: str
    updated: str
    body: str


@dataclass
class FolderEntry:
    path: str  # relative to KNOWLEDGE_DIR, forward-slash; "" for root
    items: list[Knowledge]
    folders: list[str]  # immediate child folder relative paths


@dataclass
class SearchHit:
    path: str
    title: str
    created: str
    updated: str
    snippet: str | None  # body context, None when match was title/path only
    matched_in: list[str]  # subset of ("title", "path", "body")
    score: int


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


def _ensure_root() -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)


def _resolve(rel: str, *, must_exist: bool = False) -> Path:
    """Resolve a relative path strictly under KNOWLEDGE_DIR."""
    _ensure_root()
    if rel is None:
        raise KnowledgeError("path is required")
    rel = rel.strip()
    if rel.startswith("/") or rel.startswith("\\"):
        raise KnowledgeError(f"path must be relative: {rel!r}")
    # Reject backslash-style paths to keep behavior consistent on POSIX.
    if "\\" in rel:
        raise KnowledgeError(f"path must use forward slashes: {rel!r}")
    target = (KNOWLEDGE_DIR / rel).resolve()
    root = KNOWLEDGE_DIR.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise KnowledgeError(f"path escapes knowledge dir: {rel!r}") from exc
    if must_exist and not target.exists():
        raise KnowledgeError(f"path not found: {rel!r}")
    return target


def _to_rel(p: Path) -> str:
    rel = p.resolve().relative_to(KNOWLEDGE_DIR.resolve())
    return rel.as_posix()


# ---------------------------------------------------------------------------
# Frontmatter parsing / rendering
# ---------------------------------------------------------------------------

_FM_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (meta, body). Tolerant: missing FM yields {}, full text as body."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, text
    # Find the closing '---' on its own line.
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i] == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        m = _FM_LINE.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        # Strip surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1].replace('\\"', '"').replace("\\'", "'")
        meta[key] = value
    body = "\n".join(lines[end + 1 :])
    # Preserve trailing newline if the source had one.
    if text.endswith("\n") and not body.endswith("\n"):
        body += "\n"
    return meta, body


def _render_frontmatter(meta: dict[str, str]) -> str:
    parts = ["---"]
    for key in ("id", "title", "created", "updated"):
        value = meta.get(key, "")
        # Always quote — keeps colons, hashes, quotes safe.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'{key}: "{escaped}"')
    parts.append("---")
    return "\n".join(parts) + "\n"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Title <-> slug
# ---------------------------------------------------------------------------


def slugify(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "untitled"


def _title_from(path: Path, meta: dict[str, str]) -> str:
    title = meta.get("title", "").strip()
    if title:
        return title
    return path.stem.replace("-", " ").replace("_", " ").strip() or path.stem


# ---------------------------------------------------------------------------
# Knowledge IO
# ---------------------------------------------------------------------------


def read_knowledge(rel: str) -> Knowledge:
    target = _resolve(rel, must_exist=True)
    if target.is_dir():
        raise KnowledgeError(f"path is a folder, not a knowledge entry: {rel!r}")
    text = target.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    return Knowledge(
        path=_to_rel(target),
        id=meta.get("id", ""),
        title=_title_from(target, meta),
        created=meta.get("created", ""),
        updated=meta.get("updated", ""),
        body=body,
    )


def save_knowledge(rel: str, body: str, *, title: str | None = None) -> Knowledge:
    """Create or update a knowledge entry. Auto-creates parent folders.

    Frontmatter:
      - `id` and `created` set on first save (preserved on subsequent saves).
      - `updated` bumped on every save.
      - `title` — if argument given, overwrites; else preserved; else
        derived from filename.
    """
    if not rel.endswith(".md"):
        raise KnowledgeError(f"knowledge path must end with .md: {rel!r}")
    target = _resolve(rel)
    target.parent.mkdir(parents=True, exist_ok=True)

    existing_meta: dict[str, str] = {}
    if target.exists():
        existing_text = target.read_text(encoding="utf-8")
        existing_meta, _ = _parse_frontmatter(existing_text)

    now = _now_iso()
    meta = {
        "id": existing_meta.get("id") or str(uuid.uuid4()),
        "title": (
            title.strip()
            if title is not None and title.strip()
            else existing_meta.get("title") or _title_from(target, {})
        ),
        "created": existing_meta.get("created") or now,
        "updated": now,
    }
    text = _render_frontmatter(meta) + (body if body.endswith("\n") else body + "\n")
    target.write_text(text, encoding="utf-8")
    return Knowledge(
        path=_to_rel(target),
        id=meta["id"],
        title=meta["title"],
        created=meta["created"],
        updated=meta["updated"],
        body=body if body.endswith("\n") else body + "\n",
    )


def delete_knowledge(rel: str) -> None:
    target = _resolve(rel, must_exist=True)
    if target.is_dir():
        raise KnowledgeError(f"delete_knowledge called on a folder: {rel!r}")
    target.unlink()


def move_knowledge(src: str, dst: str) -> Knowledge:
    if not dst.endswith(".md"):
        raise KnowledgeError(f"destination must end with .md: {dst!r}")
    src_p = _resolve(src, must_exist=True)
    dst_p = _resolve(dst)
    if src_p.is_dir():
        raise KnowledgeError(f"move_knowledge called on a folder: {src!r}")
    if dst_p.exists():
        raise KnowledgeError(f"destination already exists: {dst!r}")
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    src_p.rename(dst_p)
    # Bump `updated` so the move is reflected.
    item = read_knowledge(_to_rel(dst_p))
    return save_knowledge(item.path, item.body, title=item.title)


# ---------------------------------------------------------------------------
# Folder IO
# ---------------------------------------------------------------------------


def create_folder(rel: str) -> str:
    target = _resolve(rel)
    target.mkdir(parents=True, exist_ok=True)
    return _to_rel(target)


def rename_folder(src: str, dst: str) -> str:
    src_p = _resolve(src, must_exist=True)
    dst_p = _resolve(dst)
    if not src_p.is_dir():
        raise KnowledgeError(f"not a folder: {src!r}")
    if dst_p.exists():
        raise KnowledgeError(f"destination already exists: {dst!r}")
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    src_p.rename(dst_p)
    return _to_rel(dst_p)


def delete_folder(rel: str) -> None:
    """Recursively remove a folder and everything under it."""
    target = _resolve(rel, must_exist=True)
    if not target.is_dir():
        raise KnowledgeError(f"not a folder: {rel!r}")
    if target.resolve() == KNOWLEDGE_DIR.resolve():
        raise KnowledgeError("refusing to delete the knowledge root")
    shutil.rmtree(target)


# ---------------------------------------------------------------------------
# Tree walk (used by REST + system prompt injection)
# ---------------------------------------------------------------------------


def walk_tree() -> list[Knowledge]:
    """Return every knowledge entry under KNOWLEDGE_DIR, sorted by path."""
    _ensure_root()
    items: list[Knowledge] = []
    for p in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = _parse_frontmatter(text)
        items.append(
            Knowledge(
                path=_to_rel(p),
                id=meta.get("id", ""),
                title=_title_from(p, meta),
                created=meta.get("created", ""),
                updated=meta.get("updated", ""),
                body=body,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
#
# No index, no FTS, no embeddings — by design. A query reads every entry's
# body on the fly (walk_tree already loaded them). At one-user/personal
# scale that's sub-millisecond and keeps the store a plain pile of files.
#
# Weighting: a hit in the title counts most, the path next, the body least,
# with a bonus when the title starts with the query. The scalars below are
# the one place to retune relevance.

_TITLE_W = 6
_PATH_W = 3
_BODY_W = 1
_TITLE_PREFIX_BONUS = 4
_SNIPPET_RADIUS = 70


def _tokenize(query: str) -> list[str]:
    return [t for t in query.lower().split() if t]


def _updated_rank(updated: str) -> float:
    """Sort key component: more recently updated first; missing sorts last."""
    try:
        return -datetime.fromisoformat(updated.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("inf")


def _snippet(body: str, tokens: list[str]) -> str | None:
    lower = body.lower()
    at = -1
    for t in tokens:
        i = lower.find(t)
        if i != -1 and (at == -1 or i < at):
            at = i
    if at == -1:
        return None
    start = max(0, at - _SNIPPET_RADIUS)
    end = min(len(body), at + _SNIPPET_RADIUS)
    return ("…" if start > 0 else "") + body[start:end].strip() + ("…" if end < len(body) else "")


def search(query: str) -> list[SearchHit]:
    """Substring search over every entry's title, path, and body.

    AND semantics: an entry is a hit only when *every* query token appears
    somewhere in it. Results are ranked title-first (see weights above),
    then most-recently-updated, then title. A blank query yields nothing.
    """
    tokens = _tokenize(query)
    if not tokens:
        return []

    hits: list[SearchHit] = []
    for k in walk_tree():
        title = k.title.lower()
        path = k.path.lower()
        body = k.body.lower()

        if not all(t in title or t in path or t in body for t in tokens):
            continue

        score = 0
        fields: set[str] = set()
        for t in tokens:
            if t in title:
                score += _TITLE_W
                fields.add("title")
            if t in path:
                score += _PATH_W
                fields.add("path")
            if t in body:
                score += _BODY_W
                fields.add("body")
        if title.startswith(tokens[0]):
            score += _TITLE_PREFIX_BONUS

        hits.append(
            SearchHit(
                path=k.path,
                title=k.title,
                created=k.created,
                updated=k.updated,
                snippet=_snippet(k.body, tokens) if "body" in fields else None,
                matched_in=[f for f in ("title", "path", "body") if f in fields],
                score=score,
            )
        )

    # One self-evident key: score desc, then most-recently-updated, then
    # title asc. Mirrors the Storybook reference comparator.
    hits.sort(key=lambda h: (-h.score, _updated_rank(h.updated), h.title.lower()))
    return hits


def render_tree_for_prompt(items: list[Knowledge]) -> str:
    """Render the tree blob appended to the system prompt every turn.

    Format: one line per entry, "<path> — <title>". Compact and easy for
    the model to scan; no folder headers (they'd just add tokens).
    """
    if not items:
        return "(no knowledge yet)"
    return "\n".join(f"- {k.path} — {k.title}" for k in items)


def folder_index() -> dict[str, FolderEntry]:
    """Return every folder (including '') keyed by relative path.

    Used by the Knowledge screen to render the nested view: each folder
    card lists its immediate child entries and child folders.
    """
    _ensure_root()
    root_resolved = KNOWLEDGE_DIR.resolve()
    index: dict[str, FolderEntry] = {}

    def ensure(rel: str) -> FolderEntry:
        if rel not in index:
            index[rel] = FolderEntry(path=rel, items=[], folders=[])
        return index[rel]

    ensure("")
    for p in KNOWLEDGE_DIR.rglob("*"):
        try:
            rel = p.resolve().relative_to(root_resolved).as_posix()
        except ValueError:
            continue
        if p.is_dir():
            ensure(rel)
        elif p.is_file() and p.suffix == ".md":
            parent_rel = p.parent.resolve().relative_to(root_resolved).as_posix()
            if parent_rel == ".":
                parent_rel = ""
            entry = ensure(parent_rel)
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = _parse_frontmatter(text)
            entry.items.append(
                Knowledge(
                    path=rel,
                    id=meta.get("id", ""),
                    title=_title_from(p, meta),
                    created=meta.get("created", ""),
                    updated=meta.get("updated", ""),
                    body=body,
                )
            )

    # Wire children onto parents.
    for rel in list(index.keys()):
        if rel == "":
            continue
        parent_rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
        ensure(parent_rel).folders.append(rel)

    for entry in index.values():
        entry.items.sort(key=lambda k: k.title.lower())
        entry.folders.sort()
    return index
