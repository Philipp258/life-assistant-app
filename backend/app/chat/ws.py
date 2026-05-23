"""The one bidirectional client channel.

A single WebSocket per browser tab, authenticated on upgrade with the
same session cookie the REST routes use, multiplexing every chat session
the client cares about. Every turn — a user-typed message or an
autonomous/event wake — reaches the client through this channel.

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
  wake the session. A bare ``/<cmd>`` is run as a slash command
  instead.
- ``slash {session_id, name}`` — run a slash command.
- ``cancel {session_id}`` — client-side stop for the live overlay. The
  runner is not cooperatively cancelled yet; its committed result still
  reconciles via the next snapshot.

Correctness rests on the DB: the channel never carries authoritative
content it invented. A dropped delta is irrelevant (the next snapshot
supersedes it); a missed upsert is recovered by reconnect/resync or the
next fallback snapshot. Single process, in-process pubsub (AGENTS.md:
one VPS, one process) — no Redis.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Literal

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from pydantic_ai.messages import ModelRequest, UserPromptPart

from app.chat import commands, pubsub, runner
from app.chat.service import get_session, load_session_as_ui_messages, save_new_messages
from app.datetime_utils import utc_now
from app.db import SessionLocal

logger = logging.getLogger(__name__)


class _SubscribeFrame(BaseModel):
    type: Literal["subscribe"]
    session_ids: list[int] = Field(default_factory=list)


class _ResyncFrame(BaseModel):
    type: Literal["resync"]
    session_id: int


class _InputFrame(BaseModel):
    type: Literal["input"]
    session_id: int
    text: str
    voice: bool = False


class _SlashFrame(BaseModel):
    type: Literal["slash"]
    session_id: int
    name: str


class _CancelFrame(BaseModel):
    type: Literal["cancel"]
    session_id: int


_InboundFrame = Annotated[
    _SubscribeFrame | _ResyncFrame | _InputFrame | _SlashFrame | _CancelFrame,
    Field(discriminator="type"),
]
_INBOUND_ADAPTER: TypeAdapter[_InboundFrame] = TypeAdapter(_InboundFrame)

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

    # Coalesce fallback change pokes (reset, "message", rows that fold
    # into an existing UIMessage such as tool returns) into at most one
    # DB snapshot per window. Visible writes that arrive as
    # `message_upsert` bypass this.
    SNAPSHOT_COALESCE_S = 0.06

    async def pump(session_id: int) -> None:
        """Tail one session's pubsub channel into the outgoing queue.

        Subscribe first, *then* send the initial snapshot, so a write
        landing between the two is still delivered (as a redundant
        snapshot — idempotent on the client)."""
        async with pubsub.subscribe(session_id) as queue:
            await outgoing.put(_snapshot(session_id))
            # `state` is a 1-element list because the coalesced-snapshot
            # closure mutates the in-flight task handle and the dirty
            # flag, and Python closures cannot rebind outer locals from
            # inside a nested function without `nonlocal` on every
            # mutation site. Wrapping both in a small object would also
            # work; the list keeps the call sites short.
            dirty: list[bool] = [False]
            flush: list[asyncio.Task[None] | None] = [None]

            async def _coalesced_snapshot() -> None:
                try:
                    await asyncio.sleep(SNAPSHOT_COALESCE_S)
                    if dirty[0]:
                        dirty[0] = False
                        await outgoing.put(_snapshot(session_id))
                except asyncio.CancelledError:
                    pass

            try:
                while True:
                    event = await queue.get()
                    etype = event.get("type")
                    if etype in ("messages_changed", "message", "reset"):
                        dirty[0] = True
                        in_flight = flush[0]
                        if in_flight is None or in_flight.done():
                            flush[0] = asyncio.create_task(_coalesced_snapshot())
                    else:
                        # runner_finished must arrive AFTER the turn's
                        # authoritative snapshot — clients (and the WS
                        # test helper) treat it as the turn boundary. If
                        # a coalesced snapshot is still pending, emit it
                        # now, before the boundary event. Other live
                        # events (`message_upsert`, runner_started,
                        # message_start, part_delta) are forwarded
                        # immediately.
                        if etype == "runner_finished" and dirty[0]:
                            dirty[0] = False
                            in_flight = flush[0]
                            if in_flight is not None and not in_flight.done():
                                in_flight.cancel()
                            await outgoing.put(_snapshot(session_id))
                        await outgoing.put(event)
            finally:
                in_flight = flush[0]
                if in_flight is not None and not in_flight.done():
                    in_flight.cancel()

    async def sender() -> None:
        while True:
            await websocket.send_json(await outgoing.get())

    def _ensure_pump(session_id: int) -> None:
        if session_id not in pumps:
            pumps[session_id] = asyncio.create_task(pump(session_id))

    async def _handle(frame: _InboundFrame) -> None:
        """One inbound frame. Raising here must never kill the socket —
        the caller logs and keeps the connection alive."""
        if isinstance(frame, _SubscribeFrame):
            for sid in frame.session_ids:
                _ensure_pump(sid)
            return

        if isinstance(frame, _ResyncFrame):
            await outgoing.put(_snapshot(frame.session_id))
            return

        if isinstance(frame, _InputFrame):
            sid = frame.session_id
            text = frame.text.strip()
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
            runner.set_pending_voice(sid, frame.voice)
            runner.schedule_wake(sid)
            return

        if isinstance(frame, _SlashFrame):
            sid = frame.session_id
            if not _session_exists(sid):
                return
            cmd = commands.get(frame.name)
            if cmd is not None:
                # Slash handlers are quick DB stamps (e.g. /new archives
                # rows). Run inline; a slow handler would briefly block
                # only this socket's frame loop — acceptable at
                # single-user scale.
                with SessionLocal() as db:
                    cmd.handler(db, sid)
            return

        # _CancelFrame: v1 stop is a client-side overlay cancel. The
        # runner keeps going and its committed result reconciles through
        # the DB snapshot path. Real cooperative cancellation can be
        # added separately without changing the external-store ownership.

    send_task = asyncio.create_task(sender())
    try:
        while True:
            raw = await websocket.receive_json()
            try:
                frame = _INBOUND_ADAPTER.validate_python(raw)
            except ValidationError as exc:
                logger.debug("chat.ws: dropping invalid frame: %s", exc)
                continue
            try:
                await _handle(frame)
            except Exception:
                logger.exception("chat.ws: frame handling failed: %s", frame.type)
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
