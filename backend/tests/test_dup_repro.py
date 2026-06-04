"""Investigative repro for the post-task duplication (registry A1b).

Deterministic — no real model. The stub emits exactly ONE new assistant
message ("TASKUPDATE_SENTINEL") and never the laptop text. Main is
pre-seeded with a prior answered exchange ("LAPTOP_SENTINEL"). After an
event-driven main wake (two terminal tasks pending), we count how many
times each sentinel ends up persisted in the main session, and we spy
every `save_new_messages` flush the runner makes.

Reading:
- LAPTOP_SENTINEL still == 1  -> plumbing is clean; any real-world dupe
  is model behaviour (candidate #2), needs a real-model run.
- LAPTOP_SENTINEL == 2          -> plumbing bug: the runner re-persisted
  a history message as if new (candidate #1 new_messages() boundary, or
  #3 double path). The captured flush list shows the smoking gun.

Not a permanent test; delete once the cause is fixed.
"""

from __future__ import annotations

import asyncio

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo

from app.agent import get_agent
from app.chat import runner
from app.chat.models import ChatSession, Message
from app.chat.service import get_or_create_main_session, save_new_messages, save_task_handoff
from app.tasks.models import Task
from tests._function_model import build_function_model

LAPTOP = "LAPTOP_SENTINEL the laptop has no single inventor"
TASKUPDATE = "TASKUPDATE_SENTINEL here are your task results"


def _seed_terminal_task(Session, title: str, handoff: str) -> None:
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(title=title, assignee="user", chat_session_id=chat.id, is_done=False)
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        save_task_handoff(s, chat.id, handoff)


def _main_texts(Session) -> list[str]:
    out: list[str] = []
    with Session() as s:
        main_id = get_or_create_main_session(s).id
        rows = s.query(Message).filter(Message.session_id == main_id).order_by(Message.id).all()
        for r in rows:
            for part in r.parts:
                if part.part_kind in ("text", "user-prompt"):
                    c = part.payload.get("content")
                    if isinstance(c, str):
                        out.append(c)
    return out


def test_dup_repro(_test_db, monkeypatch):
    Session = _test_db

    with Session() as s:
        main_id = get_or_create_main_session(s).id
        save_new_messages(
            s,
            main_id,
            [
                ModelRequest(parts=[UserPromptPart(content="Who invented the laptop?")]),
                ModelResponse(parts=[TextPart(content=LAPTOP)]),
            ],
        )

    _seed_terminal_task(Session, "Check weather", "Cologne tomorrow: 8-15C, rain pm.")
    _seed_terminal_task(Session, "Latest OpenAI model", "Latest is GPT-5.5.")

    # Spy every flush the runner makes.
    flushes: list[tuple[int, list[str]]] = []
    real_save = runner.save_new_messages

    def spy(db, session_id, messages, **kw):
        texts: list[str] = []
        for m in messages:
            for part in getattr(m, "parts", []) or []:
                c = getattr(part, "content", None)
                if isinstance(c, str):
                    texts.append(c[:60])
        flushes.append((session_id, texts))
        return real_save(db, session_id, messages, **kw)

    monkeypatch.setattr(runner, "save_new_messages", spy)

    def handler(_msgs: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content=TASKUPDATE)])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(main_id))

    texts = _main_texts(Session)
    laptop_n = sum(1 for t in texts if LAPTOP in t)
    update_n = sum(1 for t in texts if TASKUPDATE in t)

    print("\n[wake result]:", result)
    print("[flushes to main]:", [f for f in flushes if f[0] == main_id])
    print("[all flushes]:", flushes)
    print("[main texts]:", texts)
    print(f"[LAPTOP count]={laptop_n}  [TASKUPDATE count]={update_n}")

    # The stub never emits LAPTOP. Seeded once. If it is now 2, the
    # runner re-persisted history → plumbing bug.
    assert laptop_n == 1, (
        f"LAPTOP duplicated ({laptop_n}x) — plumbing re-persisted a history "
        f"message; see [flushes to main] for which flush carried it"
    )
