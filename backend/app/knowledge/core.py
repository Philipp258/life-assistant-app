"""Core memory: two markdown files always loaded into the system prompt.

`data/core/about_user.md` — facts about the user.
`data/core/behavior.md` — assistant identity + collaboration norms.

Both are injected verbatim into the agent's system prompt every turn (see
`app.agent.__init__`). Phase 4 adds an editor screen on top of these files.

`behavior.md` also carries the assistant's name as its first non-empty line
in the form `**Name:** <name>`. The default seed below intentionally does
not satisfy that pattern — onboarding rewrites the file once the user
picks a name. See `app.knowledge.identity.resolve_assistant_name`.
"""

from __future__ import annotations

from pathlib import Path

from app.config import CORE_DIR

ABOUT_USER = "about_user"
BEHAVIOR = "behavior"

CORE_FILES = (ABOUT_USER, BEHAVIOR)


_DEFAULT_ABOUT_USER = """\
# About you

(This file is loaded verbatim into the assistant's system prompt every turn.
Replace this stub with facts about yourself — name, work, people who matter,
ongoing projects — anything you'd want the assistant to know without being
told again. Keep it tight; long context is expensive on every turn.)
"""

_DEFAULT_BEHAVIOR = """\
# How the assistant should behave

(Onboarding will rewrite this file. The first line of the post-onboarding
file is `**Name:** <name>` — that's how the rest of the app reads back
the assistant's name. Until then, defaults below apply.)

- Be direct. No filler, no sugarcoating.
- Don't hide errors or problems — surface them immediately.
- If something is ambiguous, ask rather than guess.
"""


_DEFAULTS = {
    ABOUT_USER: _DEFAULT_ABOUT_USER,
    BEHAVIOR: _DEFAULT_BEHAVIOR,
}


def core_path(name: str) -> Path:
    if name not in CORE_FILES:
        raise ValueError(f"unknown core memory file: {name!r}")
    return CORE_DIR / f"{name}.md"


def seed_if_missing() -> None:
    """Create `data/core/` and seed the two files on first run."""
    CORE_DIR.mkdir(parents=True, exist_ok=True)
    for name, default in _DEFAULTS.items():
        p = core_path(name)
        if not p.exists():
            p.write_text(default, encoding="utf-8")


def read(name: str) -> str:
    p = core_path(name)
    if not p.exists():
        return _DEFAULTS[name]
    return p.read_text(encoding="utf-8")


def write(name: str, body: str) -> None:
    p = core_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
