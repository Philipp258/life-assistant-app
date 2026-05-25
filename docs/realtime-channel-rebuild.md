# One bidirectional real-time channel — IMPLEMENTED

This was a spec for a fresh agent; it was instead implemented inline on
`task-handoff-phase2-mainchat`. Kept as the design record. The code is
the source of truth — see the module docstrings.

## What landed

**Backend**

- `app/chat/ws.py` — the single `/api/ws` WebSocket. Cookie auth on
  upgrade (WS bypasses the HTTP auth middleware; `SessionMiddleware`
  still populates the session, so the handler checks it and closes
  `4401`). Multiplexes every subscribed session. Per-frame errors are
  contained; the socket always sends a close frame on exit (a client
  blocked in receive must never hang). Unknown/!exists session in
  `input`/`slash` is a no-op.
- Protocol — down: `runner_started`, `message_start`, `part_delta`,
  `runner_finished`, and `snapshot` (the session's full visible
  UIMessage history, the authoritative view). Up: `subscribe`,
  `resync`, `input {session_id,text,voice?}`, `slash {session_id,name}`.
- `app/chat/runner.py::run_session_turn` — now token-streams every turn
  (`agent.iter` + per-model-request-node `node.stream`), publishing
  `message_start`/`part_delta`; per-node `_flush` stays authoritative.
  Consumes a one-shot `_pending_voice`. **Critically**: prepends a
  freshly built `@agent.system_prompt` itself, because pydantic-ai only
  auto-adds the system prompt for a *fresh* run and every turn here
  passes `message_history` — the deleted POST path got this from the
  Vercel adapter's reinjection. (`ReinjectSystemPrompt(replace_existing
  =True)` was tried and rejected: it eats the stall-reminder/handoff
  `SystemPromptPart`s and breaks the "history ends with a ModelRequest"
  invariant.)
- `wake_session` main gate now also fires on an unanswered trailing
  user message (`_main_has_pending_user_input`) — the input path is
  "persist user msg → `wake_session`", no per-turn HTTP.
- `app/chat/service.py::save_new_messages` publishes a coalesced
  `messages_changed` poke; the WS layer turns that into a fresh DB
  snapshot. `_serialize_message` removed.
- `app/chat/router.py` — gutted to initial-load reads (`/chat/main`,
  `/chat/sessions/{id}/messages`, `/chat/commands`) + the `/ws` route.
  Deleted: the streaming `POST /chat/messages`, the SSE
  `/chat/sessions/{id}/stream`, the REST slash POST, and all
  `_persist_native_events` / `_StreamPersistState` / voice-header
  machinery.

**Frontend**

- `chatChannel.ts` — one shared auto-reconnecting WS client.
  `useChatChannel.ts` — `useExternalStoreRuntime`; messages are React
  state the channel mutates in place (no remount); `convertChatMessage
  .ts` maps the server UIMessage → `ThreadMessageLike` (provenance under
  `metadata.custom.source`). `ChatScreen` and `TaskActivityThread` both
  migrated. Deleted `ChatStreamReload`, the `reloadKey` remount,
  `AssistantChatTransport`, the #164 reconnect banner.

## Deliberate deviation from the original spec

Resync is a **full DB snapshot per session** (sent on subscribe /
`resync` / any `messages_changed`), not an incremental
`last_msg_id` cursor replay. It is strictly stronger (always the exact
DB truth, no pairing/dedup edge cases), trivial, and fits the
single-process / single-user constraint. The DB remains the only source
of truth; the channel never carries authoritative content it invented.

## Invariants held

DB is source of truth; one turn per session (`_session_locks`,
unchanged); in-process pubsub only (no Redis); a dropped delta or missed
wake is recovered by the next snapshot.

## Tests

Backend: `tests/test_ws_channel.py` (auth, input→persist→wake→stream,
resync, autonomous-vs-input parity, single-flight) plus the migrated
`test_chat_persistence` / `test_chat_sessions_api` / `test_voice_mode_
prompt` / `test_chat_commands` / `test_eval_continuation` (all over the
channel). Frontend: `convertChatMessage.test.ts`,
`useChatChannel.test.tsx` (snapshot/draft/no-remount/onNew).
`tests/_ws.py` is the shared channel-driver helper. A
`_reset_runner_state` conftest fixture isolates the cross-loop
`asyncio.Lock`.
