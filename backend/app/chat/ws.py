"""The one bidirectional client channel.

A single WebSocket per browser tab, authenticated on upgrade with the
same session cookie the REST routes use, multiplexing every chat session
the client cares about. It replaces both halves of the old split: the
per-turn streaming POST (`/api/chat/messages`) and the server-initiated
SSE poke (`/api/chat/sessions/{id}/stream`). Every turn — a user-typed
message or an autonomous/event wake — now reaches the client the same
way.

Wire protocol
-------------
Down (server → client), each tagged with ``session_id``:

- ``runner_started`` / ``runner_finished`` — turn boundaries; drive the
  thread's running state.
- ``message_upsert`` / ``message_delete`` — keyed committed-message
  changes. The payload is the full current UIMessage for that row.
- ``message_start`` / ``part_delta`` — fallback best-effort live token
  text when a turn cannot allocate a row before commit, currently the
  main session's atomic task-event drain path.
- ``snapshot`` — the session's full visible history (the same
  UIMessage list `/api/chat/main` returns). Authoritative. Sent on
  subscribe, on `resync`, and for DB changes that cannot be represented
  as a standalone row upsert (`messages_changed` / `message` / `reset`).

Up (client → server):

- ``subscribe {session_ids}`` — start tailing these sessions; each gets
  an immediate snapshot (this *is* the connect/reconnect resync).
- ``resync {session_id}`` — re-send the snapshot from the DB.
- ``input {session_id, text, voice?}`` — persist the user message and
  wake the session. No per-turn HTTP. A bare ``/<cmd>`` is run as a
  slash command instead.
- ``slash {session_id, name}`` — run a slash command.
- ``cancel {session_id}`` — client-side stop for the live overlay. The
  current runner is not cooperatively cancelled yet; its committed
  result still reconciles via the next snapshot.

Correctness rests on the DB: the channel never carries authoritative
content it invented. A dropped delta is irrelevant (the next snapshot
supersedes it); a missed upsert is recovered by reconnect/resync or the
next fallback snapshot. Single process, in-process pubsub (AGENTS.md:
one VPS, one process) — no Redis.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic_ai.messages import ModelRequest, UserPromptPart

from app.chat import commands, pubsub, runner
from app.chat.service import get_session, load_session_as_ui_messages, save_new_messages
from app.datetime_utils import utc_now
from app.db import SessionLocal

logger = logging.getLogger(__name__)

# Custom WebSocket close code for an unauthenticated upgrade. 4000-4999
# is the application-private range; mirrors the REST 401.
WS_UNAUTHENTICATED = 4401


def _session_exists(session_id: int) -> bool:
    with SessionLocal() as db:
        return get_session(db, session_id) is not None


def _snapshot(session_id: int) -> dict[str, Any]:
    with SessionLocal() as db:
        messages = load_session_as_ui_messages(db, session_id)
    return {"type": "snapshot", "session_id": session_id, "messages": messages}


async def chat_ws(websocket: WebSocket) -> None:
    """Serve one client connection for its lifetime.

    WebSocket upgrades bypass `SessionAuthMiddleware` (it is
    HTTP-only), but `SessionMiddleware` still populates the signed
    session for the websocket scope — so the cookie check happens here.
    """
    if not websocket.session.get("uid"):
        await websocket.close(code=WS_UNAUTHENTICATED)
        return
    await websocket.accept()

    outgoing: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    pumps: dict[int, asyncio.Task[None]] = {}

    # Coalesce fallback change pokes into at most one DB snapshot per
    # window. Most visible writes now flow as `message_upsert`; snapshot
    # pokes remain for reset, legacy "message", and rows that fold into
    # an existing UIMessage such as tool returns.
    SNAPSHOT_COALESCE_S = 0.06

    async def pump(session_id: int) -> None:
        """Tail one session's pubsub channel into the outgoing queue.

        Subscribe first, *then* send the initial snapshot, so a write
        landing between the two is still delivered (as a redundant
        snapshot — idempotent on the client)."""
        async with pubsub.subscribe(session_id) as queue:
            await outgoing.put(_snapshot(session_id))
            state = {"dirty": False, "flush": None}  # type: dict[str, Any]

            async def _coalesced_snapshot() -> None:
                try:
                    await asyncio.sleep(SNAPSHOT_COALESCE_S)
                    if state["dirty"]:
                        state["dirty"] = False
                        await outgoing.put(_snapshot(session_id))
                except asyncio.CancelledError:
                    pass

            try:
                while True:
                    event = await queue.get()
                    etype = event.get("type")
                    if etype in ("messages_changed", "message", "reset"):
                        state["dirty"] = True
                        flush = state["flush"]
                        if flush is None or flush.done():
                            state["flush"] = asyncio.create_task(_coalesced_snapshot())
                    else:
                        # runner_finished must arrive AFTER the turn's
                        # authoritative snapshot — clients (and the WS
                        # test helper) treat it as the turn boundary. If
                        # a coalesced snapshot is still pending, emit it
                        # now, before the boundary event. Other live
                        # events (`message_upsert`, runner_started,
                        # message_start, part_delta) are forwarded
                        # immediately.
                        if etype == "runner_finished" and state["dirty"]:
                            state["dirty"] = False
                            flush = state["flush"]
                            if flush is not None and not flush.done():
                                flush.cancel()
                            await outgoing.put(_snapshot(session_id))
                        await outgoing.put(event)
            finally:
                flush = state["flush"]
                if flush is not None and not flush.done():
                    flush.cancel()

    async def sender() -> None:
        while True:
            await websocket.send_json(await outgoing.get())

    def _ensure_pump(session_id: int) -> None:
        if session_id not in pumps:
            pumps[session_id] = asyncio.create_task(pump(session_id))

    def _sid(data: dict[str, Any]) -> int | None:
        try:
            return int(data["session_id"])
        except (KeyError, TypeError, ValueError):
            return None

    async def _handle(data: dict[str, Any]) -> None:
        """One inbound frame. Raising here must never kill the socket —
        the caller logs and keeps the connection alive."""
        mtype = data.get("type")

        if mtype == "subscribe":
            for raw in data.get("session_ids", []) or []:
                try:
                    _ensure_pump(int(raw))
                except (TypeError, ValueError):
                    continue

        elif mtype == "resync":
            sid = _sid(data)
            if sid is not None:
                await outgoing.put(_snapshot(sid))

        elif mtype == "input":
            sid = _sid(data)
            if sid is None:
                return
            text = (data.get("text") or "").strip()
            if not text:
                return
            cmd_name = commands.parse_command(text)
            cmd = commands.get(cmd_name) if cmd_name else None
            if cmd is not None:
                if _session_exists(sid):
                    with SessionLocal() as db:
                        cmd.handler(db, sid)
                return
            if not _session_exists(sid):
                return
            with SessionLocal() as db:
                save_new_messages(
                    db,
                    sid,
                    [ModelRequest(parts=[UserPromptPart(content=text, timestamp=utc_now())])],
                )
            runner.set_pending_voice(sid, bool(data.get("voice")))
            runner.schedule_wake(sid)

        elif mtype == "slash":
            sid = _sid(data)
            if sid is None or not _session_exists(sid):
                return
            cmd = commands.get(data.get("name"))
            if cmd is not None:
                # Slash handlers are quick DB stamps (e.g. /new archives
                # rows). Run inline; a slow handler would briefly block
                # only this socket's frame loop — acceptable at
                # single-user scale.
                with SessionLocal() as db:
                    cmd.handler(db, sid)

        elif mtype == "cancel":
            # v1 stop is a client-side overlay cancel. The runner keeps
            # going and its committed result reconciles through the DB
            # snapshot path. Real cooperative cancellation can be added
            # separately without changing the external-store ownership.
            return

    send_task = asyncio.create_task(sender())
    try:
        while True:
            data = await websocket.receive_json()
            if not isinstance(data, dict):
                continue
            try:
                await _handle(data)
            except Exception:
                logger.exception("chat.ws: frame handling failed: %r", data.get("type"))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("chat.ws: connection loop failed")
    finally:
        send_task.cancel()
        for task in pumps.values():
            task.cancel()
        # Always send a close frame, even if the loop bailed on an
        # unexpected error — otherwise a client blocked in receive would
        # hang forever instead of seeing the disconnect.
        try:
            await websocket.close()
        except Exception:
            pass
