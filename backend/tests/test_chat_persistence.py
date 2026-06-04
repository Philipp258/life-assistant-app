"""Regression tests for chat-message persistence over the channel.

Historical failure modes still guarded here, now exercised through the
one WebSocket (`app.chat.ws`) instead of the deleted streaming POST:

1. Issue #40: a pending task-terminal event drained on a user turn used
   to silently drop the user's prompt (slice math vs. pydantic-ai
   stripping synthetic parts). The user prompt + the agent reply must
   both persist even when the main session also drains a peer handoff
   on that same turn.

2. Task #164: a turn must be bracketed by `runner_started` /
   `runner_finished` so the client can tell "still working" from
   "stopped" — the channel forwards both verbatim.

3. Interrupted-turn repair: a dangling ToolCallPart from a previously
   killed turn gets a synthetic ToolReturnPart so the next history load
   validates (unchanged — module-level, no transport).
"""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
)
from pydantic_ai.models.function import AgentInfo

from app.chat.models import ChatSession, Message
from app.chat.service import save_new_messages, save_task_handoff
from app.tasks.models import Task
from tests._ws import reduced_texts, ws_turn


def test_user_prompt_persists_with_pending_task_event(client, _test_db):
    """Issue #40 over the channel: a peer task recorded a terminal
    handoff, so the main session drains a `task_updates` event on this
    very user turn. Both the user's prompt and the agent reply must
    survive."""
    Session = _test_db

    main_id = client.get("/api/chat/main").json()["session_id"]
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(title="Peer task", assignee="user", chat_session_id=chat.id)
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        target_id = chat.id
    with Session() as s:
        save_task_handoff(s, target_id, "event from peer")

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="agent reply")])

    events = ws_turn(client, session_id=main_id, text="hello nix", handler=handler)

    user_texts: list[str] = []
    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == main_id).order_by(Message.id).all()
        roles = [r.role for r in rows]
        for r in rows:
            if r.role != "request":
                continue
            for part in r.parts:
                if part.part_kind == "user-prompt":
                    user_texts.append(part.payload.get("content"))
    assert "request" in roles, f"user prompt not persisted; roles={roles}"
    assert "response" in roles, f"agent reply not persisted; roles={roles}"
    assert "hello nix" in user_texts

    assert "hello nix" in reduced_texts(events, "user")
    assert "agent reply" in reduced_texts(events, "assistant")


def test_turn_brackets_runner_started_and_finished(client, _test_db):
    """Task #164: every turn is bracketed by `runner_started` before the
    agent dispatch and `runner_finished` once persistence settles."""
    main_id = client.get("/api/chat/main").json()["session_id"]

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="hi back")])

    events = ws_turn(client, session_id=main_id, text="hi", handler=handler)
    types = [e.get("type") for e in events]
    assert "runner_started" in types, types
    assert "runner_finished" in types, types
    assert types.index("runner_started") < types.index("runner_finished")


def test_repair_persisted_history_appends_synthetic_tool_returns(_test_db):
    """A dangling ToolCallPart left over from an interrupted turn gets a
    synthetic ToolReturnPart-only ModelRequest appended, so the next
    pydantic-ai history load validates."""
    from pydantic_ai.messages import (
        ModelRequest,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    from app.chat.repair import repair_persisted_history

    Session = _test_db
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.commit()
        s.refresh(chat)
        sid = chat.id

        save_new_messages(
            s,
            sid,
            [
                ModelRequest(parts=[UserPromptPart(content="hi")]),
                ModelResponse(parts=[ToolCallPart(tool_name="x", args={}, tool_call_id="a")]),
            ],
        )

    with Session() as s:
        wrote = repair_persisted_history(s, sid)
    assert wrote is True

    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == sid).order_by(Message.id).all()
        assert [r.role for r in rows] == ["request", "response", "request"]
        last_parts = [p.payload for p in rows[-1].parts]
    tool_returns = [p for p in last_parts if p.get("part_kind") == "tool-return"]
    assert len(tool_returns) == 1
    assert tool_returns[0]["tool_call_id"] == "a"

    with Session() as s:
        wrote_again = repair_persisted_history(s, sid)
    assert wrote_again is False

    with Session() as s:
        balanced_chat = ChatSession()
        s.add(balanced_chat)
        s.commit()
        s.refresh(balanced_chat)
        balanced_id = balanced_chat.id

        save_new_messages(
            s,
            balanced_id,
            [
                ModelRequest(parts=[UserPromptPart(content="hi")]),
                ModelResponse(parts=[ToolCallPart(tool_name="x", args={}, tool_call_id="b")]),
                ModelRequest(parts=[ToolReturnPart(tool_name="x", tool_call_id="b", content="ok")]),
            ],
        )
    with Session() as s:
        wrote_balanced = repair_persisted_history(s, balanced_id)
    assert wrote_balanced is False
