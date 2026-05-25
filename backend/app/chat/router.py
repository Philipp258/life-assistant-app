"""Chat endpoints — initial reads + the one bidirectional channel.

Phase 5: there is exactly one main chat (the singleton `task_id IS NULL`
session). Multi-chat affordances were dropped — `GET /api/chat/main`
replaces the old session list, and there is no longer a way to spawn a
new general session.

Turn delivery is no longer request/response. The REST routes here only
serve the *initial* page load (full hydrated history) and the slash
command list. Everything live — sending a message, streaming the reply,
autonomous task wakes finishing, slash commands — runs over the single
WebSocket in `app.chat.ws`. There is no streaming POST and no SSE.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket

from app.chat import commands
from app.chat.service import (
    get_session,
    inject_onboarding_greeting_if_needed,
    load_main_session_as_ui_messages,
    load_session_as_ui_messages,
)
from app.chat.ws import chat_ws
from app.db import SessionLocal
from app.users.service import is_onboarding

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/chat/main")
def chat_main() -> dict[str, Any]:
    """The singleton main session and its full hydrated history.

    Side effect: on a fresh install (user not onboarded + no messages
    yet), a hardcoded assistant greeting is inserted before history is
    loaded so the user lands on a chat that already feels alive. The
    write is idempotent.
    """
    with SessionLocal() as session:
        inject_onboarding_greeting_if_needed(session)
        sid, messages = load_main_session_as_ui_messages(session)
    return {
        "session_id": sid,
        "messages": messages,
        "is_onboarding": is_onboarding(),
    }


@router.get("/chat/sessions/{session_id}/messages")
def chat_session_messages(session_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        chat = get_session(session, session_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = load_session_as_ui_messages(session, session_id)
    return {"session_id": session_id, "messages": messages}


@router.get("/chat/commands")
def chat_commands_list() -> dict[str, list[dict[str, str]]]:
    """Available slash commands. Frontend renders these in the composer menu."""
    return {
        "commands": [
            {"name": c.name, "description": c.description} for c in commands.all_commands()
        ]
    }


@router.websocket("/ws")
async def chat_ws_route(websocket: WebSocket) -> None:
    await chat_ws(websocket)
