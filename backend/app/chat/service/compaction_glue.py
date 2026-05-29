"""Bridge between live-history loading and the `compaction` module."""

from __future__ import annotations

from collections.abc import Callable

from pydantic_ai.messages import ModelMessage
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.chat import compaction
from app.chat.models import Message
from app.chat.service.history import _load_live_messages
from app.chat.service.writes import save_new_messages
from app.config import settings
from app.db import SessionLocal
from app.datetime_utils import utc_now


def _persist_compaction_result(
    session: Session,
    session_id: int,
    rows: list[Message],
    result: compaction.CompactionResult,
) -> None:
    """Stamp compacted rows + persist the new summary message row."""
    compacted_count = len(result.compacted_messages)
    now = utc_now()
    for row in rows[:compacted_count]:
        row.compacted_at = now
    session.flush()
    assert result.summary_message is not None
    # Compaction summaries are stripped from `_dump_ui_messages`, so SSE
    # listeners would refetch only to see the same visible history. Skip
    # the publish to avoid spurious runtime re-mounts.
    save_new_messages(session, session_id, [result.summary_message], publish=False)


def _visible_cursor(session: Session, session_id: int) -> int:
    return (
        session.scalar(
            select(func.max(Message.id)).where(
                Message.session_id == session_id,
                Message.archived_at.is_(None),
            )
        )
        or 0
    )


def load_compacted_history(
    session: Session,
    session_id: int,
    *,
    summarizer: Callable[[str], str] | None = None,
    trigger_tokens: int | None = None,
    keep_groups: int | None = None,
) -> list[ModelMessage]:
    """Sync variant of compacted-history loading. Used by tests and any
    fully sync entry point.

    Calls `compaction.compact`, which uses `Agent.run_sync()` for the
    default summarizer. Do not call this from inside an async event
    loop — use `aload_compacted_history` instead, which awaits the
    LLM call so the loop stays responsive.
    """
    rows, messages = _load_live_messages(session, session_id)
    if not rows:
        return []

    result = compaction.compact(
        messages,
        trigger_tokens=trigger_tokens or settings.compaction_trigger_tokens,
        keep_groups=keep_groups or settings.compaction_keep_groups,
        summarizer=summarizer,
    )
    if not result.did_compact or result.summary_message is None:
        return messages

    _persist_compaction_result(session, session_id, rows, result)
    return [result.summary_message, *result.kept_messages]


async def aload_compacted_history(
    session: Session,
    session_id: int,
    *,
    summarizer: compaction.SummarizerFn | None = None,
    trigger_tokens: int | None = None,
    keep_groups: int | None = None,
) -> list[ModelMessage]:
    """Load live history (rows where compacted_at IS NULL) and run
    token-aware compaction in place.

    If the live history exceeds `compaction_trigger_tokens`, the older
    portion is summarized via the configured chat model and replaced
    with a single summary message row. Compacted rows are stamped with
    `compacted_at` so future loads exclude them, but they stay in the
    DB (still visible to the user, queryable for archival tooling).

    Result: list of ModelMessages ready to pass as `message_history`.
    The cache prefix is stable between compaction events, so the
    upstream provider can cache it across turns.

    The DB calls remain sync (microsecond-fast); only the LLM round
    trip is awaited. This mirrors the rest of the codebase's pattern
    of sync DB inside async handlers.
    """
    rows, messages = _load_live_messages(session, session_id)
    if not rows:
        return []

    result = await compaction.acompact(
        messages,
        trigger_tokens=trigger_tokens or settings.compaction_trigger_tokens,
        keep_groups=keep_groups or settings.compaction_keep_groups,
        summarizer=summarizer,
    )
    if not result.did_compact or result.summary_message is None:
        return messages

    _persist_compaction_result(session, session_id, rows, result)
    return [result.summary_message, *result.kept_messages]


async def aload_compacted_history_with_cursor(
    session: Session,
    session_id: int,
    *,
    summarizer: compaction.SummarizerFn | None = None,
    trigger_tokens: int | None = None,
    keep_groups: int | None = None,
) -> tuple[list[ModelMessage], int]:
    """Task-chat history loader: compact like main, and return a row cursor.

    The cursor is taken after compaction, so a freshly inserted summary row
    does not look like new user input to the stale-input guard.
    """
    messages = await aload_compacted_history(
        session,
        session_id,
        summarizer=summarizer,
        trigger_tokens=trigger_tokens,
        keep_groups=keep_groups,
    )
    return messages, _visible_cursor(session, session_id)


async def force_compact_history(session_id: int) -> bool:
    """Best-effort compaction used after a provider context-window error."""
    with SessionLocal() as session:
        before = _visible_cursor(session, session_id)
        await aload_compacted_history(
            session,
            session_id,
            trigger_tokens=1,
            keep_groups=settings.compaction_keep_groups,
        )
        after = _visible_cursor(session, session_id)
        # A new summary row means compaction happened. Stamping old rows
        # without a summary would be a bug in the compactor.
        return after > before
