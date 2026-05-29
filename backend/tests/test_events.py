"""Task-terminal event feed (`app.chat.events`).

There is no subscription graph anymore: the singleton main session
implicitly drains *every* task-terminal handoff via one high-water
cursor (`ChatSession.event_cursor_id`). These cover:

- only the main session consumes; task chats never do,
- a handoff from any task reaches main — including a task main never
  created (the routine/recurrence/improve-life-assistant bug),
- exactly-once: once the cursor advances, a re-drain (incl. a simulated
  process restart reading the persisted cursor) yields nothing,
- archived handoff rows are skipped,
- the migration adds the cursor column and drops the old table, and
  round-trips down/up.
"""

from __future__ import annotations

from pydantic_ai import models

from app.chat import events
from app.chat.models import ChatSession
from app.chat.service import get_or_create_main_session, save_task_handoff
from app.datetime_utils import utc_now
from app.tasks.models import Task

models.ALLOW_MODEL_REQUESTS = False


def _task_chat(Session, *, title: str = "A task") -> int:
    """A bare task + its chat (no subscription, no creator) — the exact
    shape a routine / recurrence / improve-life-assistant task has."""
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(title=title, assignee="assistant", chat_session_id=chat.id)
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        return chat.id


def _handoff_blob(messages) -> str:
    """Flatten the synthetic injection's user-role report content."""
    from pydantic_ai.messages import UserPromptPart

    out = []
    for m in messages:
        for p in getattr(m, "parts", []) or []:
            if isinstance(p, UserPromptPart):
                out.append(str(p.content))
    return "\n".join(out)


def test_main_with_no_handoffs_drains_nothing(_test_db):
    Session = _test_db
    with Session() as s:
        main_id = get_or_create_main_session(s).id
        injected, seen = events.drain_terminal_events(s, main_id)
    assert injected == []
    assert seen == []
    with Session() as s:
        assert events.has_undrained_events(s, main_id) is False
        assert events.latest_terminal_event_id(s) is None


def test_task_chat_is_not_a_consumer(_test_db):
    """A task chat never drains events — even if handoffs exist."""
    Session = _test_db
    chat_id = _task_chat(Session)
    with Session() as s:
        save_task_handoff(s, chat_id, "blocked on user")
    with Session() as s:
        injected, seen = events.drain_terminal_events(s, chat_id)
    assert (injected, seen) == ([], [])
    with Session() as s:
        assert events.has_undrained_events(s, chat_id) is False


def test_handoff_from_any_task_reaches_main(_test_db):
    """The routine/recurrence/improve-life-assistant bug: main was only ever
    subscribed to tasks it created, so autonomous tasks never surfaced.
    Now a handoff from a task main never touched still drains to main."""
    Session = _test_db
    chat_id = _task_chat(Session, title="Weekly disk check")
    with Session() as s:
        row = save_task_handoff(s, chat_id, "Disk at 71%, nothing urgent.")
        assert row is not None
        assert row.compacted_at is not None
        main_id = get_or_create_main_session(s).id

    with Session() as s:
        assert events.has_undrained_events(s, main_id) is True
        injected, seen = events.drain_terminal_events(s, main_id)

    assert len(seen) == 1
    blob = _handoff_blob(injected)
    assert "Weekly disk check" in blob
    assert "Disk at 71%, nothing urgent." in blob
    assert "/tasks/" in blob  # link line present


def test_all_task_origins_drain_in_one_pass(_test_db):
    Session = _test_db
    a = _task_chat(Session, title="Task A")
    b = _task_chat(Session, title="Task B")
    with Session() as s:
        save_task_handoff(s, a, "A is done")
        save_task_handoff(s, b, "B needs input")
        main_id = get_or_create_main_session(s).id

    with Session() as s:
        injected, seen = events.drain_terminal_events(s, main_id)
    assert len(seen) == 2
    blob = _handoff_blob(injected)
    assert "A is done" in blob and "B needs input" in blob


def test_cursor_exactly_once_and_restart_safe(_test_db):
    Session = _test_db
    chat_id = _task_chat(Session)
    with Session() as s:
        save_task_handoff(s, chat_id, "first handoff")
        main_id = get_or_create_main_session(s).id

    # Drain + advance, exactly like a finished main turn.
    with Session() as s:
        injected, seen = events.drain_terminal_events(s, main_id)
        assert len(seen) == 1
        events.advance_event_cursor(s, main_id, seen=seen)

    # Same process, second turn: nothing new.
    with Session() as s:
        injected2, seen2 = events.drain_terminal_events(s, main_id)
    assert (injected2, seen2) == ([], [])

    # Simulated restart: a brand-new Session reads the persisted cursor
    # off the row, so the already-seen handoff is still not re-injected.
    with Session() as s:
        fresh_main = get_or_create_main_session(s).id
        assert s.get(ChatSession, fresh_main).event_cursor_id is not None
        injected3, seen3 = events.drain_terminal_events(s, fresh_main)
    assert (injected3, seen3) == ([], [])

    # A new handoff after the cursor still surfaces.
    with Session() as s:
        save_task_handoff(s, chat_id, "second handoff")
    with Session() as s:
        injected4, seen4 = events.drain_terminal_events(s, main_id)
    assert len(seen4) == 1
    assert "second handoff" in _handoff_blob(injected4)
    assert "first handoff" not in _handoff_blob(injected4)


def test_archived_handoff_rows_are_skipped(_test_db):
    Session = _test_db
    chat_id = _task_chat(Session)
    with Session() as s:
        row = save_task_handoff(s, chat_id, "stale handoff")
        row.archived_at = utc_now()
        s.commit()
        main_id = get_or_create_main_session(s).id
    with Session() as s:
        injected, seen = events.drain_terminal_events(s, main_id)
    assert (injected, seen) == ([], [])


def test_non_handoff_rows_do_not_count(_test_db):
    """A normal user/assistant message in a task chat is not a terminal
    event — only the hidden `<task_handoff>` row is."""
    from pydantic_ai.messages import ModelResponse, TextPart

    from app.chat.service import save_new_messages

    Session = _test_db
    chat_id = _task_chat(Session)
    with Session() as s:
        save_new_messages(s, chat_id, [ModelResponse(parts=[TextPart(content="progress note")])])
        main_id = get_or_create_main_session(s).id
    with Session() as s:
        assert events.has_undrained_events(s, main_id) is False
        injected, seen = events.drain_terminal_events(s, main_id)
    assert (injected, seen) == ([], [])


# ---------------------------------------------------------------------------
# Triage prompt + silence output tool
# ---------------------------------------------------------------------------


def test_injection_prompt_frames_triage_and_silence(_test_db):
    """The drained report must (a) frame itself as not-a-user-request,
    (b) tell the model it may stay silent via `do_nothing` for routine
    internal status, (c) default to surfacing when unsure, and (d) forbid
    re-answering earlier conversation."""
    Session = _test_db
    chat_id = _task_chat(Session, title="Nightly backup")
    with Session() as s:
        save_task_handoff(s, chat_id, "Backup ok, nothing to report.")
        main_id = get_or_create_main_session(s).id
    with Session() as s:
        injected, seen = events.drain_terminal_events(s, main_id)
    text = _handoff_blob(injected)
    assert seen
    assert "not a message from the user" in text
    assert "do_nothing" in text
    assert "routine internal status" in text
    assert "unsure, surface" in text
    assert "do not re-answer or continue earlier conversation" in text
    # No standing "always reply" mandate (the old noise bug).
    assert "Reply to the user with what they need to know" not in text


def test_silence_output_tool_shape():
    """`SILENCE_OUTPUT` is a no-field, run-ending output tool named
    `do_nothing` whose value type the runner can identify."""
    spec = events.SILENCE_OUTPUT
    assert spec.name == "do_nothing"
    assert spec.output is events.StaySilent
    assert events.StaySilent.model_fields == {}
    assert isinstance(events.StaySilent(), events.StaySilent)
