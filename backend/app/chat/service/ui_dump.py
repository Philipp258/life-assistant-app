"""Render persisted ModelMessages as the UIMessage list shown to the frontend."""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
)
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.models import Message
from app.chat.service.history import _is_compaction_summary_message, _load_rows_and_messages
from app.chat.service.sessions import get_or_create_main_session
from app.datetime_utils import serialize_utc
from app.tasks.models import Task

logger = logging.getLogger(__name__)


def _resolve_task_provenance(
    session: Session, source_session_ids: set[int]
) -> dict[int, dict[str, Any]]:
    """For each source session id that is a task chat, return its provenance.

    Provenance shape mirrors what the frontend renders: `type='task'`,
    plus the task id + a snapshot of the current title. Sessions that
    aren't task-bound get no entry. Looked up live so renamed tasks
    show their current title; deleted tasks simply drop the source line.
    """
    if not source_session_ids:
        return {}
    rows = session.scalars(select(Task).where(Task.chat_session_id.in_(source_session_ids))).all()
    out: dict[int, dict[str, Any]] = {}
    for task in rows:
        out[task.chat_session_id] = {
            "type": "task",
            "task_id": task.id,
            "task_title": task.title,
            "source_session_id": task.chat_session_id,
        }
    return out


def _dump_ui_messages(
    session: Session, rows: list[Message], messages: list[ModelMessage]
) -> list[dict[str, Any]]:
    """Build the UIMessage list shown to the frontend.

    Stamps `metadata.source` on assistant UIMessages whose persisted row
    is tagged with a different originating session (a cross-session
    relay, e.g. `relay_to_task`), so the UI can render a "From task: …"
    provenance line linking back to that task.
    """
    pairs = [(r, m) for r, m in zip(rows, messages) if not _is_compaction_summary_message(m)]
    visible_messages = [m for _, m in pairs]
    ui_messages = VercelAIAdapter.dump_messages(visible_messages, sdk_version=6)

    # `dump_messages` preserves source order: assistant UIMessages line
    # up with ModelResponse rows, and user UIMessages line up with
    # ModelRequest rows that carry a UserPromptPart. Tool-return-only
    # requests fold into the preceding assistant UIMessage and should
    # not get a standalone id. Stamp the DB row id so reconnect/snapshot
    # reconciliation has stable identity instead of the adapter's
    # regenerated synthetic ids.
    def _aligned(rows_side: list[Message], indices: list[int], label: str) -> dict[int, Message]:
        if len(rows_side) == len(indices):
            return dict(zip(indices, rows_side))
        logger.warning(
            "chat.dump: %s row/UIMessage count mismatch (%d rows, %d messages) "
            "for session %s; skipping stable ids for %s",
            label,
            len(rows_side),
            len(indices),
            rows[0].session_id if rows else "?",
            label,
        )
        return {}

    response_rows = [r for r, m in pairs if isinstance(m, ModelResponse)]
    user_request_rows = [
        r
        for r, m in pairs
        if isinstance(m, ModelRequest) and any(isinstance(p, UserPromptPart) for p in m.parts)
    ]
    assistant_indices = [i for i, ui in enumerate(ui_messages) if ui.role == "assistant"]
    user_indices = [i for i, ui in enumerate(ui_messages) if ui.role == "user"]
    row_for_ui: dict[int, Message] = {
        **_aligned(response_rows, assistant_indices, "assistant"),
        **_aligned(user_request_rows, user_indices, "user"),
    }

    provenance = _resolve_task_provenance(
        session,
        {r.source_session_id for r in row_for_ui.values() if r.source_session_id is not None},
    )

    out: list[dict[str, Any]] = []
    for idx, ui in enumerate(ui_messages):
        if ui.role == "system":
            continue
        dumped = ui.model_dump(mode="json", by_alias=True)
        row = row_for_ui.get(idx)
        if row is not None:
            dumped["id"] = str(row.id)
            dumped["createdAt"] = serialize_utc(row.created_at)
            if row.source_session_id is not None:
                source = provenance.get(row.source_session_id)
                if source is not None:
                    existing = dumped.get("metadata") or {}
                    dumped["metadata"] = {**existing, "source": source}
        out.append(dumped)
    return out


def load_session_as_ui_messages(session: Session, session_id: int) -> list[dict[str, Any]]:
    rows, messages = _load_rows_and_messages(session, session_id)
    return _dump_ui_messages(session, rows, messages)


def load_main_session_as_ui_messages(
    session: Session,
) -> tuple[int, list[dict[str, Any]]]:
    main = get_or_create_main_session(session)
    rows, messages = _load_rows_and_messages(session, main.id)
    return main.id, _dump_ui_messages(session, rows, messages)


def _ui_message_by_row_id(
    session: Session,
    session_id: int,
    row_id: int,
) -> dict[str, Any] | None:
    row_id_text = str(row_id)
    for message in load_session_as_ui_messages(session, session_id):
        if message.get("id") == row_id_text:
            return message
    return None
