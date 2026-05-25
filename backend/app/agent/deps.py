"""Run-time dependencies passed to the chat agent.

Tools that need to know which session they're running in receive this
through `RunContext[AgentDeps]`. Legacy paths (single-chat) can pass
`AgentDeps(session_id=None)` — those tools simply skip session-scoped
behavior when the id is missing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDeps:
    session_id: int | None = None
    # Per-request hint: the assistant's reply will be spoken via TTS, so
    # `build_system_prompt` appends a short "answer in spoken style" line
    # *after* the cached portion. Left at the tail so the cache prefix
    # for the static prompt + memory + tree is byte-identical on every
    # turn — only the last ~1 chunk differs when voice mode flips.
    voice_mode: bool = False
