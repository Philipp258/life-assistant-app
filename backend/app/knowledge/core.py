"""Core memory: two markdown files always loaded into the system prompt.

`data/core/about_user.md` — facts about the user (work, interests, people
who matter, ongoing projects).
`data/core/behavior.md` — tone and collaboration norms for the assistant.

Both are injected verbatim into the agent's system prompt every turn (see
`app.agent.__init__`). Identity (the assistant's name and the user's name)
is structured and stored separately in ``app_settings``; do not write names
into these files. See `app.knowledge.identity`.
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
Replace this stub with facts about yourself — work, people who matter,
ongoing projects — anything you'd want the assistant to know without being
told again. Your name is stored separately as structured identity, not here.
Keep it tight; long context is expensive on every turn.)
"""

_DEFAULT_BEHAVIOR = """\
# How the assistant should behave

(Onboarding will rewrite this file with tone and collaboration norms in your
own words. The assistant's name lives in structured identity, not here.
Defaults below apply until onboarding runs.)

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
