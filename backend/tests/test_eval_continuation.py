"""End-to-end behavior evals against a real (cheap) model.

Opt-in (`pytest -m eval`), real model via OpenRouter. These drive the
*real* main-chat interface — an `input` over the `/api/ws` channel,
exactly what the UI hits — not the autonomous task runner directly. A
failure here is signal about real behavior; print output is kept so a
human can eyeball it.

Scenarios:
- delegation: a research/slow request must become an assistant task,
  not get answered inline (issue #213).
- continuation: a blocked task's handoff surfaces in main chat; the
  user answers there; the answer is relayed into the task and it
  resumes.

Run:
    OPENROUTER_API_KEY=... uv run pytest backend/tests/test_eval_continuation.py -m eval -s
Skips cleanly if the key is absent.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from app.agent import invalidate_agent
from app.chat import runner
from app.chat.models import ChatSession, Message
from app.chat.service import get_or_create_main_session, save_task_handoff
from app.tasks.models import Task

EVAL_MODEL = os.environ.get("EVAL_MODEL", "deepseek/deepseek-v4-flash")


@pytest.fixture
def eval_db(_test_db):
    """`_test_db`, but the provider row points at a real cheap OpenRouter
    model so `get_agent()` runs against a live model. Skips if no key."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        pytest.skip("OPENROUTER_API_KEY not set — behavior eval skipped")

    Session = _test_db
    from app.provider_settings.models import ProviderSettings

    with Session() as db:
        row = db.get(ProviderSettings, 1)
        assert row is not None
        row.zai_api_key = None
        row.openrouter_api_key = key
        row.openrouter_chat_model = EVAL_MODEL
        row.preferred_chat_provider = "openrouter"
        db.commit()

    invalidate_agent()  # drop any agent built with the zai test creds
    yield Session
    invalidate_agent()  # next test rebuilds fresh


@pytest.fixture
def eval_client(eval_db):
    """Authenticated TestClient built *after* the OpenRouter provider is
    seeded, so requests run the real agent against the live model."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"password": "test-pass"})
        assert r.status_code == 200, r.text
        yield c


def _post_user_message(client, text: str, *, session_id: int | None = None) -> None:
    """One real main-chat turn over the WebSocket channel — the exact
    path the UI uses. Drains down-events until the turn settles."""
    sid = session_id
    if sid is None:
        sid = client.get("/api/chat/main").json()["session_id"]

    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "subscribe", "session_ids": [sid]})
        first = ws.receive_json()
        assert first["type"] == "snapshot", first
        ws.send_json({"type": "input", "session_id": sid, "text": text})
        for _ in range(500):
            event = ws.receive_json()
            if event.get("type") == "runner_finished":
                return
        raise AssertionError("real-model turn did not finish within 500 events")


def _assistant_texts(Session, session_id: int) -> list[str]:
    with Session() as s:
        rows = (
            s.query(Message)
            .filter(Message.session_id == session_id, Message.kind == "response")
            .order_by(Message.id)
            .all()
        )
    out: list[str] = []
    for row in rows:
        for part in (row.parts_json or {}).get("parts", []) or []:
            if isinstance(part, dict) and part.get("part_kind") == "text":
                c = part.get("content")
                if isinstance(c, str) and c.strip():
                    out.append(c.strip())
    return out


def _seed_blocked_task(Session, *, title: str, handoff: str) -> tuple[int, int]:
    """A task blocked on the user (assignee='user', not done) with a
    recorded question handoff — the terminal state the runner leaves
    before the main-chat handoff wake. This is what's *continuable*; a
    completed task has nothing to relay into."""
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(
            title=title,
            assignee="user",
            chat_session_id=chat.id,
            is_done=False,
        )
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        task_id, chat_id = task.id, chat.id
        save_task_handoff(s, chat_id, handoff)
    return task_id, chat_id


@pytest.mark.eval
def test_delegation_research_request_becomes_task(eval_db, eval_client):
    """A research/slow request should be delegated as an assistant task,
    not ground out inline. Reproduces issue #213."""
    Session = eval_db
    with Session() as s:
        main_id = get_or_create_main_session(s).id
        tasks_before = s.query(Task).count()

    _post_user_message(eval_client, "Please find out the latest models by OpenAI.")

    with Session() as s:
        new_tasks = s.query(Task).order_by(Task.id).offset(tasks_before).all()

    print("[main reply]:", _assistant_texts(Session, main_id))
    print("[tasks created]:", [(t.title, t.assignee) for t in new_tasks])

    assert new_tasks, (
        "research request was not delegated — agent answered it inline "
        "instead of creating a task (issue #213)"
    )
    assert any(t.assignee == "assistant" for t in new_tasks), (
        "a task was created but not assignee='assistant' — it won't run in the background"
    )


@pytest.mark.eval
def test_continuation_relay(eval_db, eval_client):
    Session = eval_db
    task_id, task_chat_id = _seed_blocked_task(
        Session,
        title="Draft the supplier follow-up email",
        handoff=(
            "Drafted the follow-up email and saved it. Could not confirm "
            "the Berlin office hours — need that before sending."
        ),
    )

    with Session() as s:
        main_id = get_or_create_main_session(s).id

    # Part 1: the task recorded a terminal handoff; the main session
    # drains it on its next turn and surfaces it. This is the real,
    # unified path — no separate handoff agent.
    result = asyncio.run(runner.wake_session(main_id))
    assert result.outcome == "completed", result.outcome
    main_after_handoff = _assistant_texts(Session, main_id)
    print("\n[handoff → main chat]:", main_after_handoff)
    assert main_after_handoff, (
        "handoff wake produced no main-chat message — agent dismissed an "
        "actionable handoff (it needs info to proceed)"
    )

    with Session() as s:
        task_msgs_before = s.query(Message).filter(Message.session_id == task_chat_id).count()

    # Part 2+3: user answers in main chat via the real endpoint; the
    # main agent should relay it into the task and resume it.
    _post_user_message(
        eval_client, "Berlin office is open 9–17 CET, Mon–Fri. Go ahead and send it."
    )

    with Session() as s:
        task_msgs_after = s.query(Message).filter(Message.session_id == task_chat_id).count()
        task = s.get(Task, task_id)

    print("[main turn → task texts]:", _assistant_texts(Session, task_chat_id))
    print("[task.assignee]:", task.assignee, "[task.is_done]:", task.is_done)

    assert task_msgs_after > task_msgs_before, (
        "main agent did not relay the user's answer into the task chat "
        "(expected a relay_to_task write)"
    )
    assert task.assignee == "assistant", (
        "main agent relayed but did not resume the task "
        "(expected assignee flipped back to 'assistant')"
    )


@pytest.mark.eval
def test_event_wake_does_not_duplicate_prior_answer(eval_db):
    """Registry A1b: an autonomous main wake (background tasks finished)
    surfaces the updates as ONE normal reply and must NOT re-answer an
    already-answered prior message. Real model — the turn-shape fix is
    model-behavioural, the deterministic repro can't prove it."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )

    from app.chat.service import save_new_messages

    Session = eval_db
    sentinel = "Adam Osborne and the Osborne 1"
    with Session() as s:
        main_id = get_or_create_main_session(s).id
        save_new_messages(
            s,
            main_id,
            [
                ModelRequest(parts=[UserPromptPart(content="Who invented the laptop?")]),
                ModelResponse(parts=[TextPart(content=f"No single inventor — {sentinel}, 1981.")]),
            ],
        )
    _seed_blocked_task(Session, title="Check weather", handoff="Cologne tomorrow: 8-15C, rain pm.")
    _seed_blocked_task(Session, title="Latest OpenAI model", handoff="Latest is GPT-5.5.")

    before = _assistant_texts(Session, main_id)
    asyncio.run(runner.wake_session(main_id))
    after = _assistant_texts(Session, main_id)
    new = after[len(before) :]

    print("[new main messages]:", new)
    sentinel_n = sum(1 for t in after if sentinel in t)

    assert new, "event wake produced no main reply (surfaced via a tool side-effect? A1a)"
    assert sentinel_n == 1, (
        f"prior answer duplicated ({sentinel_n}x) — autonomous wake re-answered "
        f"an already-answered message (A1b regression)"
    )
    blob = " ".join(new).lower()
    assert any(k in blob for k in ("weather", "cologne", "openai", "gpt")), (
        "task updates were not surfaced in the reply"
    )
