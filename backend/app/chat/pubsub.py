"""In-process pub/sub keyed by session_id.

Events are dropped on slow consumers (bounded queue, drop-oldest). Single
process only — cross-process delivery would need redis pubsub or similar.

Used for:
- SSE clients tailing a session's stream
- Cross-session event injection (subscribers see target events) — Phase 7
- Wake-up triggers for the autonomous task-chat runner — Phase 6
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

_subscribers: dict[int, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
_QUEUE_MAX = 256


def publish(session_id: int, event: dict[str, Any]) -> None:
    """Deliver `event` to every subscriber of `session_id`.

    Synchronous so it can be called from sync save paths. Drops oldest on
    overflow rather than blocking.
    """
    for q in list(_subscribers.get(session_id, ())):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                q.get_nowait()
            with suppress(asyncio.QueueFull):
                q.put_nowait(event)


@asynccontextmanager
async def subscribe(session_id: int) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
    """Subscribe to events for a session for the lifetime of the with-block."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers[session_id].add(queue)
    try:
        yield queue
    finally:
        _subscribers[session_id].discard(queue)
        if not _subscribers[session_id]:
            _subscribers.pop(session_id, None)


def subscriber_count(session_id: int) -> int:
    return len(_subscribers.get(session_id, ()))
