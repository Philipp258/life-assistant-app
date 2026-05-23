"""Session + message persistence for Pydantic AI ModelMessages.

`parts_json` stores the full `ModelMessage` JSON (round-trips through
`ModelMessagesTypeAdapter`). A few fields are denormalized into typed columns
for indexed queries, but the JSON is the source of truth.

Phase 5: there is exactly one **main** session — the singleton row with
`task_id IS NULL`. It is the app's home. Task-bound sessions belong to
their tasks. The historical multi-chat affordances were dropped here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.chat import compaction, pubsub
from app.chat.models import ChatSession, Message
from app.config import settings
from app.datetime_utils import serialize_utc, utc_now
from app.tasks.models import Task

TASK_HANDOFF_OPEN = "<task_handoff>"
TASK_HANDOFF_CLOSE = "</task_handoff>"

logger = logging.getLogger(__name__)


def get_or_create_main_session(session: Session) -> ChatSession:
    """Singleton main session (`kind='main'`).

    Picks the oldest matching session as canonical when multiple exist
    (defensive — the migration backfills exactly one main row).
    """
    row = session.scalars(
        select(ChatSession)
        .where(ChatSession.kind == "main")
        .order_by(ChatSession.id.asc())
        .limit(1)
    ).first()
    if row is not None:
        return row
    row = ChatSession(kind="main")
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def get_session(session: Session, session_id: int) -> ChatSession | None:
    return session.get(ChatSession, session_id)


def _load_rows_and_messages(
    session: Session, session_id: int
) -> tuple[list[Message], list[ModelMessage]]:
    """Read visible rows + their decoded ModelMessages.

    Archived rows (stamped by `/new`) are hidden from UI and agent.
    The originals stay in the DB and are reachable via the agent's
    `search_main_chat_history` tool. Compacted rows (stamped by
    main-chat compaction) stay visible to the user — only the agent's
    live loader filters those out.
    """
    rows = session.scalars(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.archived_at.is_(None),
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).all()
    if not rows:
        return [], []
    parsed = list(ModelMessagesTypeAdapter.validate_python([row.parts_json for row in rows]))
    return list(rows), parsed


def _load_model_messages(session: Session, session_id: int) -> list[ModelMessage]:
    _rows, messages = _load_rows_and_messages(session, session_id)
    return messages


def load_session_history(session: Session, session_id: int) -> list[ModelMessage]:
    return _load_model_messages(session, session_id)


def load_session_history_with_cursor(
    session: Session, session_id: int
) -> tuple[list[ModelMessage], int]:
    rows, messages = _load_rows_and_messages(session, session_id)
    cursor = rows[-1].id if rows else 0
    return messages, cursor


def _is_compaction_summary_message(message: ModelMessage) -> bool:
    if not isinstance(message, ModelRequest):
        return False
    parts = message.parts or []
    if len(parts) != 1 or not isinstance(parts[0], UserPromptPart):
        return False
    content = parts[0].content
    return isinstance(content, str) and content.lstrip().startswith("<conversation_summary>")


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


def _publish_message_upsert(
    session_id: int,
    message: dict[str, Any],
    *,
    run_id: str | None = None,
) -> None:
    event: dict[str, Any] = {
        "type": "message_upsert",
        "session_id": session_id,
        "message": message,
    }
    if run_id is not None:
        event["run_id"] = run_id
    pubsub.publish(session_id, event)


def _publish_row_upsert(
    session: Session,
    session_id: int,
    row_id: int,
    *,
    run_id: str | None = None,
) -> bool:
    message = _ui_message_by_row_id(session, session_id, row_id)
    if message is None:
        return False
    _publish_message_upsert(session_id, message, run_id=run_id)
    return True


def publish_streaming_text_upsert(
    session_id: int,
    row_id: int,
    text: str,
    *,
    run_id: str | None = None,
) -> None:
    """Publish a live text-only assistant message with its persisted row id."""
    _publish_message_upsert(
        session_id,
        {
            "id": str(row_id),
            "role": "assistant",
            "parts": [{"type": "text", "text": text}],
        },
        run_id=run_id,
    )


def create_streaming_response_row(session: Session, session_id: int, text: str) -> Message:
    """Create the DB identity for a streaming assistant response.

    This intentionally does not fire push notifications. The row starts
    as a best-effort live partial; the final ModelResponse update is what
    represents a completed assistant message.
    """
    blob = ModelMessagesTypeAdapter.dump_python(
        [ModelResponse(parts=[TextPart(content=text)])],
        mode="json",
    )[0]
    row = Message(
        session_id=session_id,
        kind=blob.get("kind", "response"),
        parts_json=blob,
        usage_json=blob.get("usage"),
        model_name=blob.get("model_name"),
        provider=blob.get("provider_name"),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_streaming_response_row(
    session: Session,
    row_id: int,
    message: ModelResponse,
    *,
    publish: bool = True,
    run_id: str | None = None,
) -> Message | None:
    """Replace a live partial response row with the final ModelResponse."""
    row = session.get(Message, row_id)
    if row is None or row.kind != "response":
        return None

    blob = ModelMessagesTypeAdapter.dump_python([message], mode="json")[0]
    row.parts_json = blob
    row.usage_json = blob.get("usage")
    row.model_name = blob.get("model_name")
    row.provider = blob.get("provider_name")
    flag_modified(row, "parts_json")
    session.commit()
    session.refresh(row)

    main_session_id = get_or_create_main_session(session).id
    if row.session_id == main_session_id:
        _fire_assistant_message_push(row, row.session_id)
    if publish and not _publish_row_upsert(session, row.session_id, row.id, run_id=run_id):
        pubsub.publish(row.session_id, {"type": "messages_changed", "session_id": row.session_id})
    return row


def _load_live_messages(
    session: Session, session_id: int
) -> tuple[list[Message], list[ModelMessage]]:
    """Read uncompacted rows and decode their stored ModelMessages.

    Returns the row list (so callers can stamp `compacted_at` on
    specific rows) alongside the parsed ModelMessage list.
    """
    rows = session.scalars(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.compacted_at.is_(None),
            Message.archived_at.is_(None),
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).all()
    if not rows:
        return [], []
    parsed = list(ModelMessagesTypeAdapter.validate_python([row.parts_json for row in rows]))
    paired = list(zip(rows, parsed, strict=True))
    # Summary rows are inserted after the live tail in DB order, but they
    # represent the oldest context. Keep row/message alignment while presenting
    # summaries first to the agent and to later compaction passes.
    paired.sort(
        key=lambda item: (
            not _is_compaction_summary_message(item[1]),
            item[0].created_at,
            item[0].id,
        )
    )
    return [row for row, _message in paired], [message for _row, message in paired]


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


def load_compacted_history(
    session: Session,
    session_id: int,
    *,
    summarizer: Callable[[str], str] | None = None,
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
        trigger_tokens=settings.compaction_trigger_tokens,
        keep_groups=settings.compaction_keep_groups,
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
) -> list[ModelMessage]:
    """Load live history (rows where compacted_at IS NULL) and run
    token-aware compaction in place.

    If the live history exceeds `compaction_trigger_tokens`, the older
    portion is summarized via the configured chat model and replaced
    with a single summary message row. Compacted rows are stamped with
    `compacted_at` so they no longer feed into future loads, but stay
    in the DB (still visible to the user, queryable for archival
    tooling).

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
        trigger_tokens=settings.compaction_trigger_tokens,
        keep_groups=settings.compaction_keep_groups,
        summarizer=summarizer,
    )
    if not result.did_compact or result.summary_message is None:
        return messages

    _persist_compaction_result(session, session_id, rows, result)
    return [result.summary_message, *result.kept_messages]


def save_new_messages(
    session: Session,
    session_id: int,
    messages: Iterable[ModelMessage],
    *,
    source_session_id: int | None = None,
    publish: bool = True,
) -> list[Message]:
    """Persist messages and publish each to the session's pubsub channel.

    `source_session_id` is stamped on every persisted row — set when the
    message originates from a *different* session via cross-session tooling.

    `publish=False` suppresses the pubsub fan-out when the writer's client
    is already seeing the same content via another channel — e.g. the chat
    router's streaming-event tap saves draft response rows from the same
    events the connected client is rendering, so re-publishing would only
    cause that client to re-fetch and re-mount its runtime. Push
    notifications still fire (they consult `subscriber_count` directly).
    """
    dumped = ModelMessagesTypeAdapter.dump_python(list(messages), mode="json")
    saved: list[Message] = []
    for blob in dumped:
        row = Message(
            session_id=session_id,
            source_session_id=source_session_id,
            kind=blob.get("kind", "request"),
            parts_json=blob,
        )
        if blob.get("kind") == "response":
            row.usage_json = blob.get("usage")
            row.model_name = blob.get("model_name")
            row.provider = blob.get("provider_name")
        session.add(row)
        saved.append(row)
    session.commit()
    main_session_id: int | None = None
    has_response = any(blob.get("kind") == "response" for blob in dumped)
    if has_response:
        # Only resolve main when there's actually a candidate to push for.
        # Looked up once per call so we don't hammer SELECT in fan-out.
        main_session_id = get_or_create_main_session(session).id
    for row in saved:
        session.refresh(row)
        if row.kind == "response" and session_id == main_session_id:
            _fire_assistant_message_push(row, session_id)
    if publish:
        # Prefer keyed row updates over a full snapshot. Some rows (tool
        # returns, hidden system context) do not map to standalone UI
        # messages; those still fall back to the snapshot poke because
        # they can change a previous assistant UIMessage's tool state.
        needs_snapshot = False
        for row in saved:
            if not _publish_row_upsert(session, session_id, row.id):
                needs_snapshot = True
        if needs_snapshot:
            pubsub.publish(session_id, {"type": "messages_changed", "session_id": session_id})
    return saved


def _extract_text_preview(row: Message, max_len: int = 140) -> str:
    """Build a short body string for a push notification from a saved row.

    Pulls the first text part out of the persisted Pydantic AI JSON blob.
    Falls back to an empty string if no text is found (e.g. a tool-only
    response). The push fan-out skips empty bodies.
    """
    parts = row.parts_json.get("parts", []) if isinstance(row.parts_json, dict) else []
    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = part.get("part_kind") or part.get("kind")
        if kind in ("text", "TextPart"):
            content = part.get("content")
            if isinstance(content, str) and content.strip():
                text = content.strip()
                if len(text) > max_len:
                    text = text[: max_len - 1].rstrip() + "…"
                return text
    return ""


def _fire_assistant_message_push(row: Message, session_id: int) -> None:
    """Schedule a Web Push notification for a freshly-saved assistant message.

    Hidden import + centralized scheduling keeps this fire-and-forget:
    `save_new_messages` is sync (called from sync routes and from the
    runner via thread executors) and must not block on network I/O.
    """
    body = _extract_text_preview(row)
    if not body:
        return

    from app.notifications import service as notify_service

    notify_service.schedule_notify(
        event_type="assistant_message",
        title="Life Assistant",
        body=body,
        url="/chat",
        quiet_if_session_id=session_id,
        tag=f"assistant_message:{session_id}",
    )


def save_run_messages(
    session: Session,
    new_messages: list[ModelMessage],
    *,
    session_id: int,
    publish: bool = True,
) -> None:
    """Persist a run's new_messages to the given session."""
    save_new_messages(
        session,
        session_id,
        [m for m in new_messages if isinstance(m, ModelResponse) or m.kind == "request"],
        publish=publish,
    )


def format_task_handoff(handoff: str) -> str:
    """Wrap a task lifecycle handoff as hidden model context."""
    text = (handoff or "").strip()
    return f"{TASK_HANDOFF_OPEN}\n{text}\n{TASK_HANDOFF_CLOSE}"


def save_task_handoff(
    session: Session,
    session_id: int,
    handoff: str,
) -> Message | None:
    """Persist a task lifecycle handoff as hidden agent-visible context.

    The row is a valid ModelRequest containing only a SystemPromptPart,
    so normal UI rendering hides it. It is the task-terminal *event*: the
    main session drains it into a synthetic user-role report on its next
    turn (`app.chat.events`).
    """
    text = (handoff or "").strip()
    if not text:
        return None
    message = ModelRequest(parts=[SystemPromptPart(content=format_task_handoff(text))])
    rows = save_new_messages(session, session_id, [message], publish=False)
    return rows[0] if rows else None


def extract_task_handoff_text(content: str) -> str | None:
    text = (content or "").strip()
    if not text.startswith(TASK_HANDOFF_OPEN):
        return None
    body = text[len(TASK_HANDOFF_OPEN) :].strip()
    if body.endswith(TASK_HANDOFF_CLOSE):
        body = body[: -len(TASK_HANDOFF_CLOSE)].strip()
    return body or None


def latest_task_handoff(session: Session, session_id: int) -> str | None:
    """Return the newest hidden handoff string for a task chat."""
    rows = session.scalars(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.archived_at.is_(None),
        )
        .order_by(Message.id.desc())
        .limit(50)
    ).all()
    for row in rows:
        raw: dict[str, Any] = row.parts_json if isinstance(row.parts_json, dict) else {}
        parts = raw.get("parts", []) or []
        for part in parts:
            if not isinstance(part, dict):
                continue
            kind = part.get("part_kind") or part.get("kind")
            if kind not in ("system-prompt", "SystemPromptPart"):
                continue
            content = part.get("content")
            if not isinstance(content, str):
                continue
            handoff = extract_task_handoff_text(content)
            if handoff is not None:
                return handoff
    return None


ONBOARDING_GREETING = (
    "Welcome! I'm your new personal assistant. I'll keep track of tasks, "
    "remember what matters, and adapt to how you like to work. To get "
    "started — what would you like to call me?"
)


def inject_onboarding_greeting_if_needed(session: Session) -> bool:
    """Insert a hardcoded assistant greeting into the main session iff the
    user is mid-onboarding and the main session has no messages yet.

    Idempotent: once any message exists in the main session, this is a
    no-op. Returns True if a row was inserted, False otherwise.
    """
    from app.users.service import is_onboarding

    if not is_onboarding():
        return False
    main = get_or_create_main_session(session)
    existing = session.scalars(
        select(Message).where(Message.session_id == main.id).limit(1)
    ).first()
    if existing is not None:
        return False
    greeting = ModelResponse(parts=[TextPart(content=ONBOARDING_GREETING)])
    save_new_messages(session, main.id, [greeting])
    return True


# ---------------------------------------------------------------------------
# Streaming-write helpers
#
# The chat router persists agent output as it streams from pydantic-ai
# (rather than once at end-of-turn) so a mid-stream disconnect or
# provider timeout doesn't lose the partial response. The helpers below
# back that flow: insert a row at the first `PartEndEvent`, rewrite its
# `parts_json` as later events extend the message, and patch the final
# metadata (usage / model / provider) once the stream resolves.
#
# pubsub is intentionally silent here — the active HTTP client already
# streams the deltas; cross-tab listeners refetch on `runner_finished`
# (router-side) or on the runner's existing per-message publishes
# (runner-side, which keeps using `save_new_messages` directly).
# ---------------------------------------------------------------------------


def _dump_single(message: ModelMessage) -> dict[str, Any]:
    """Round-trip one ModelMessage to the JSON blob shape stored in `parts_json`."""
    dumped = ModelMessagesTypeAdapter.dump_python([message], mode="json")
    blob = dumped[0]
    if not isinstance(blob, dict):  # pragma: no cover — adapter always returns dicts
        raise TypeError(f"ModelMessagesTypeAdapter dumped non-dict: {type(blob).__name__}")
    return blob


def _assign_response_metadata_columns(row: Message, blob: dict[str, Any]) -> None:
    row.usage_json = blob.get("usage")
    row.model_name = blob.get("model_name")
    row.provider = blob.get("provider_name")


def start_draft_response(
    session: Session,
    session_id: int,
    response: ModelResponse,
    *,
    source_session_id: int | None = None,
) -> Message:
    """Insert a partial assistant response row mid-stream.

    The row is fully-formed (carries whatever parts have completed so
    far); subsequent `update_draft_response` calls overwrite the parts
    blob as new `PartEndEvent`s arrive. Push notifications fire only at
    `finalize_response_metadata`, not here.
    """
    blob = _dump_single(response)
    row = Message(
        session_id=session_id,
        source_session_id=source_session_id,
        kind="response",
        parts_json=blob,
    )
    _assign_response_metadata_columns(row, blob)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_draft_response(
    session: Session,
    message_id: int,
    response: ModelResponse,
) -> None:
    """Overwrite `parts_json` for an in-flight response row."""
    blob = _dump_single(response)
    row = session.get(Message, message_id)
    if row is None:
        return
    row.parts_json = blob
    _assign_response_metadata_columns(row, blob)
    flag_modified(row, "parts_json")
    session.commit()


def start_tool_return_request(
    session: Session,
    session_id: int,
    request: ModelRequest,
    *,
    source_session_id: int | None = None,
) -> Message:
    """Insert a ModelRequest row holding the first ToolReturnPart of a turn."""
    blob = _dump_single(request)
    row = Message(
        session_id=session_id,
        source_session_id=source_session_id,
        kind="request",
        parts_json=blob,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_tool_return_request(
    session: Session,
    message_id: int,
    request: ModelRequest,
) -> None:
    """Overwrite `parts_json` for an in-flight ToolReturnPart-carrying request."""
    blob = _dump_single(request)
    row = session.get(Message, message_id)
    if row is None:
        return
    row.parts_json = blob
    flag_modified(row, "parts_json")
    session.commit()


def finalize_response_metadata(
    session: Session,
    message_id: int,
    response: ModelResponse,
    *,
    fire_push: bool = True,
) -> Message | None:
    """Patch a draft response row with the final ModelResponse + side effects.

    The final ModelResponse carries `usage` / `model_name` /
    `provider_name`, which aren't present on per-PartEndEvent draft
    inserts. This call writes them in and (optionally) fires the
    assistant-message Web Push that `save_new_messages` would have
    triggered if we'd persisted the whole turn at once.
    """
    blob = _dump_single(response)
    row = session.get(Message, message_id)
    if row is None:
        return None
    row.parts_json = blob
    _assign_response_metadata_columns(row, blob)
    flag_modified(row, "parts_json")
    session.commit()
    session.refresh(row)
    if fire_push:
        main_session_id = get_or_create_main_session(session).id
        if row.session_id == main_session_id:
            _fire_assistant_message_push(row, row.session_id)
    return row
