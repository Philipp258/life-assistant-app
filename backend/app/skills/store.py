"""Skill store: disk operations + prompt rendering.

A skill is a directory containing a `SKILL.md` file with YAML
frontmatter (`name`, `description`) and a markdown body. The folder
name must match `^[a-z0-9][a-z0-9-]*$`. Folders without `SKILL.md` are
silently skipped. Malformed frontmatter degrades: missing `name` falls
back to the folder name, missing `description` becomes empty string.

Skills come from two sources:

- `DEFAULTS_SKILLS_DIR` (`backend/defaults/skills/`) — tracked in git,
  ships with the app, read-only at runtime (the agent's filesystem
  tools refuse writes there).
- `SKILLS_DIR` (`data/skills/`) — user-installed, fully editable.

A user skill cannot share a name with a default; the default takes
priority on collision (defensive — `add-skills` is supposed to enforce
this at install time).

The frontmatter parser is reused from `app.knowledge.store` to avoid
duplicating tolerant YAML-ish parsing logic.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.config import DEFAULTS_SKILLS_DIR, SKILLS_DIR
from app.knowledge.store import _parse_frontmatter

SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SkillSource = Literal["default", "user"]

log = logging.getLogger(__name__)


class SkillError(Exception):
    """Raised on bad skill names or missing skills."""


@dataclass
class SkillMeta:
    name: str
    description: str
    path: str  # POSIX path relative to repo root
    source: SkillSource


@dataclass
class Skill:
    name: str
    description: str
    path: str
    body: str
    source: SkillSource


def _validate_name(name: str) -> None:
    if not name or not SKILL_NAME_RE.match(name):
        raise SkillError(f"invalid skill name: {name!r}")


def _rel_path(p: Path) -> str:
    """Return POSIX path relative to repo root, for surfacing in API + prompt."""
    from app.config import REPO_ROOT

    try:
        return p.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def _walk_dir(root: Path, source: SkillSource) -> list[SkillMeta]:
    """Walk one source directory; return a SkillMeta for each valid SKILL.md."""
    if not root.exists():
        return []
    out: list[SkillMeta] = []
    for child in sorted(root.iterdir(), key=lambda c: c.name):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, _body = _parse_frontmatter(text)
        name = meta.get("name") or child.name
        description = meta.get("description") or ""
        out.append(
            SkillMeta(
                name=name,
                description=description,
                path=_rel_path(skill_md),
                source=source,
            )
        )
    return out


def list_skills() -> list[SkillMeta]:
    """Merge defaults + user skills, sort by name.

    Default-name collision: the user copy is dropped with a warning.
    Tolerant: missing fields fall back to safe defaults; folders without
    SKILL.md are skipped silently.
    """
    defaults = _walk_dir(DEFAULTS_SKILLS_DIR, "default")
    user = _walk_dir(SKILLS_DIR, "user")
    default_names = {m.name for m in defaults}

    merged: list[SkillMeta] = list(defaults)
    for m in user:
        if m.name in default_names:
            log.warning(
                "user skill %r at %s shadows a default; ignoring",
                m.name,
                m.path,
            )
            continue
        merged.append(m)

    merged.sort(key=lambda m: m.name)
    return merged


def read_skill(name: str) -> Skill:
    """Read a single skill by name. Defaults take priority over user copies."""
    _validate_name(name)
    for source, root in (("default", DEFAULTS_SKILLS_DIR), ("user", SKILLS_DIR)):
        p = root / name / "SKILL.md"
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        return Skill(
            name=meta.get("name") or name,
            description=meta.get("description") or "",
            path=_rel_path(p),
            body=body,
            source=source,  # type: ignore[arg-type]
        )
    raise SkillError(f"skill not found: {name!r}")


def render_skills_for_prompt(metas: list[SkillMeta]) -> str:
    """Compact footer block for the system prompt.

    Format is fixed and sorted-by-name (already done by `list_skills`)
    so the prompt prefix stays cache-stable across turns when no skills
    have been installed/edited. Each entry surfaces the SKILL.md's
    real path so the agent can `read_file` it directly — defaults live
    under `backend/defaults/skills/`, user installs under `data/skills/`,
    and the activation instructions in the system prompt rely on this
    per-skill path rather than guessing a single root.
    """
    if not metas:
        return "<skills>(none installed)</skills>"
    lines = ["<skills>"]
    for m in metas:
        desc = m.description.strip().replace("\n", " ")
        head = f"{m.name}: {desc}" if desc else m.name
        lines.append(f"  - {head} (read {m.path})")
    lines.append("</skills>")
    return "\n".join(lines)
