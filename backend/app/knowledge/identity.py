"""Resolve the assistant's name from `data/core/behavior.md`.

Convention: onboarding writes `**Name:** <name>` as the first non-empty
line of behavior.md. The system prompt and frontend label both call
`resolve_assistant_name()` to read it back. Until onboarding runs, the
default seed text doesn't satisfy the regex and the fallback returns
"Assistant" — that's the unbranded period before the user picks a name.
"""

from __future__ import annotations

import re

from app.knowledge import core as core_memory

NAME_RE = re.compile(r"^\s*\*\*Name:\*\*\s+(.+?)\s*$")

FALLBACK_NAME = "Assistant"

_SCAN_LINES = 8


def resolve_assistant_name() -> str:
    body = core_memory.read(core_memory.BEHAVIOR)
    for line in body.splitlines()[:_SCAN_LINES]:
        m = NAME_RE.match(line)
        if m:
            return m.group(1).strip()
    return FALLBACK_NAME
