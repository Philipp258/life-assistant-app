"""Session + message persistence for Pydantic AI ModelMessages.

`parts_json` stores the full `ModelMessage` JSON (round-trips through
`ModelMessagesTypeAdapter`). A few fields are denormalized into typed columns
for indexed queries, but the JSON is the source of truth.

Phase 5: there is exactly one **main** session — the singleton row with
`task_id IS NULL`. It is the app's home. Task-bound sessions belong to
their tasks. The historical multi-chat affordances were dropped here.

The implementation is split across submodules (`sessions`, `history`,
`ui_dump`, `publish`, `push`, `writes`, `streaming`, `compaction_glue`,
`handoff`, `onboarding`). This module re-exports the public surface so
existing `from app.chat.service import …` callers keep working.
"""

from __future__ import annotations

from app.chat.service.compaction_glue import (
    aload_compacted_history,
    aload_compacted_history_with_cursor,
    force_compact_history,
    load_compacted_history,
)
from app.chat.service.handoff import (
    TASK_HANDOFF_CLOSE,
    TASK_HANDOFF_OPEN,
    extract_task_handoff_text,
    format_task_handoff,
    latest_task_handoff,
    save_task_handoff,
)
from app.chat.service.history import (
    load_session_history,
    load_session_history_with_cursor,
    parse_message,
)
from app.chat.service.onboarding import (
    ONBOARDING_GREETING,
    inject_onboarding_greeting_if_needed,
)
from app.chat.service.publish import publish_streaming_text_upsert
from app.chat.service.push import _fire_assistant_message_push as _fire_assistant_message_push
from app.chat.service.sessions import get_or_create_main_session, get_session
from app.chat.service.streaming import (
    create_streaming_response_row,
    finalize_response_metadata,
    start_draft_response,
    start_tool_return_request,
    update_draft_response,
    update_streaming_response_row,
    update_tool_return_request,
)
from app.chat.service.ui_dump import (
    load_main_session_as_ui_messages,
    load_session_as_ui_messages,
)
from app.chat.service.writes import save_new_messages, save_run_messages

__all__ = [
    "ONBOARDING_GREETING",
    "TASK_HANDOFF_CLOSE",
    "TASK_HANDOFF_OPEN",
    "aload_compacted_history",
    "aload_compacted_history_with_cursor",
    "create_streaming_response_row",
    "extract_task_handoff_text",
    "finalize_response_metadata",
    "format_task_handoff",
    "force_compact_history",
    "get_or_create_main_session",
    "get_session",
    "inject_onboarding_greeting_if_needed",
    "latest_task_handoff",
    "load_compacted_history",
    "load_main_session_as_ui_messages",
    "load_session_as_ui_messages",
    "load_session_history",
    "load_session_history_with_cursor",
    "parse_message",
    "publish_streaming_text_upsert",
    "save_new_messages",
    "save_run_messages",
    "save_task_handoff",
    "start_draft_response",
    "start_tool_return_request",
    "update_draft_response",
    "update_streaming_response_row",
    "update_tool_return_request",
]
