"""Agent-tool behavior tests.

Exercises the plain `do_*` functions (which is what `@agent.tool_plain`
ends up wrapping) so we don't need a live model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agent.tools.tasks import (
    _update_task_tool_kwargs,
    do_complete_task,
    do_create_task,
    do_delete_task,
    do_get_task,
    do_list_tasks,
    do_reassign_task,
    do_reschedule_task,
    do_update_task,
)
from app.chat.models import ChatSession, Message


@pytest.mark.usefixtures("_test_db")
def test_do_create_task_defaults_assignee_assistant():
    out = do_create_task(title="Write a book")
    assert out["title"] == "Write a book"
    # No do_at, no interval, assigned to assistant → state is 'running'.
    assert out["state"] == "running"
    assert out["is_done"] is False
    # The agent tool defaults assignee='assistant' (the assistant is taking it on).
    assert out["assignee"] == "assistant"
    # Auto-creates a chat session for the task.
    assert isinstance(out["chat_session_id"], int)


@pytest.mark.usefixtures("_test_db")
def test_do_create_task_explicit_user_assignee():
    out = do_create_task(title="Your move", assignee="user")
    assert out["assignee"] == "user"
    assert out["state"] == "yours"


@pytest.mark.usefixtures("_test_db")
def test_do_create_task_scheduled():
    out = do_create_task(title="Ping", do_at=datetime(2099, 4, 27, 14, 30))
    # Future do_at on an assistant-owned task → state is 'up_next'.
    assert out["state"] == "up_next"
    assert out["do_at"].startswith("2099-04-27T14:30")


@pytest.mark.usefixtures("_test_db")
def test_do_create_task_scheduled_does_not_wake_immediately(monkeypatch):
    scheduled: list[int] = []

    def fake_schedule_wake(session_id: int) -> None:
        scheduled.append(session_id)

    monkeypatch.setattr("app.chat.runner.schedule_wake", fake_schedule_wake)

    out = do_create_task(title="Ping later", do_at=datetime.now(UTC) + timedelta(hours=1))

    assert out["state"] == "up_next"
    assert scheduled == []


@pytest.mark.usefixtures("_test_db")
def test_do_create_task_immediate_assistant_task_wakes(monkeypatch):
    scheduled: list[int] = []

    def fake_schedule_wake(session_id: int) -> None:
        scheduled.append(session_id)

    monkeypatch.setattr("app.chat.runner.schedule_wake", fake_schedule_wake)

    out = do_create_task(title="Ping now")

    assert out["state"] == "running"
    assert scheduled == [out["chat_session_id"]]


@pytest.mark.usefixtures("_test_db")
def test_do_create_task_recurring_defaults_count():
    out = do_create_task(title="Stretch", interval_unit="day")
    # No do_at on a recurring assistant task → first run is now → state 'running'.
    assert out["state"] == "running"
    assert out["interval_unit"] == "day"
    assert out["interval_count"] == 1  # defaulted


@pytest.mark.usefixtures("_test_db")
def test_do_create_task_recurring_explicit_count():
    out = do_create_task(title="Big review", interval_unit="week", interval_count=2)
    assert out["interval_count"] == 2


@pytest.mark.usefixtures("_test_db")
def test_do_list_tasks_filters_by_done_and_assignee():
    a = do_create_task(title="a", assignee="assistant")
    b = do_create_task(title="b", assignee="user")
    do_complete_task(b["id"], handoff="b is done")

    all_tasks = do_list_tasks()
    assert all_tasks["total"] == 2
    assert len(all_tasks["tasks"]) == 2

    open_tasks = do_list_tasks(is_done=False)
    assert [t["id"] for t in open_tasks["tasks"]] == [a["id"]]

    done_tasks = do_list_tasks(is_done=True)
    assert [t["id"] for t in done_tasks["tasks"]] == [b["id"]]

    assistant_tasks = do_list_tasks(assignee="assistant")
    assert [t["id"] for t in assistant_tasks["tasks"]] == [a["id"]]


@pytest.mark.usefixtures("_test_db")
def test_do_list_tasks_paginates_losslessly():
    created = {do_create_task(title=f"t{i}", assignee="assistant")["id"] for i in range(7)}

    first = do_list_tasks(limit=3)
    assert first["total"] == 7
    assert len(first["tasks"]) == 3
    assert first["has_more"] is True
    assert first["next_offset"] == 3

    seen: list[int] = [t["id"] for t in first["tasks"]]
    offset = first["next_offset"]
    guard = 0
    while offset is not None:
        page = do_list_tasks(limit=3, offset=offset)
        seen.extend(t["id"] for t in page["tasks"])
        offset = page["next_offset"]
        guard += 1
        assert guard < 100, "task paging failed to terminate"

    # Every task reached exactly once by stepping next_offset — no
    # dupes, nothing dropped between pages.
    assert len(seen) == len(set(seen)) == 7
    assert set(seen) == created

    # Offset past the end is an empty terminal page, not an error.
    tail = do_list_tasks(limit=3, offset=999)
    assert tail["tasks"] == []
    assert tail["total"] == 7
    assert tail["has_more"] is False
    assert tail["next_offset"] is None


@pytest.mark.usefixtures("_test_db")
def test_do_complete_task_unknown_returns_error():
    out = do_complete_task(9999, handoff="nothing to do")
    assert "error" in out


@pytest.mark.usefixtures("_test_db")
def test_do_reassign_task_flips_assignee():
    task = do_create_task(title="Hand off")
    assert task["assignee"] == "assistant"

    flipped = do_reassign_task(task["id"], assignee="user", handoff="needs user input")
    assert flipped["assignee"] == "user"

    flipped_back = do_reassign_task(task["id"], assignee="assistant", handoff="assistant resumes")
    assert flipped_back["assignee"] == "assistant"


@pytest.mark.usefixtures("_test_db")
def test_do_reassign_task_unknown_returns_error():
    out = do_reassign_task(9999, assignee="user", handoff="missing task")
    assert "error" in out


@pytest.mark.usefixtures("_test_db")
def test_complete_task_does_not_auto_post_to_main():
    """Terminal task tools no longer auto-post to main chat — the main
    session surfaces it by draining the recorded handoff on its next
    turn (`app.chat.events`), not the tool as a side effect."""
    from app.chat.models import Message
    from app.chat.service import get_or_create_main_session
    from app.db import SessionLocal

    task = do_create_task(title="Reminder: groceries")
    do_complete_task(task["id"], handoff="groceries reminder handled")

    with SessionLocal() as s:
        main = get_or_create_main_session(s)
        msgs = s.query(Message).filter(Message.session_id == main.id).all()
    assert msgs == []


@pytest.mark.usefixtures("_test_db")
def test_complete_task_records_hidden_handoff():
    from app.chat.service import latest_task_handoff, load_session_as_ui_messages
    from app.db import SessionLocal

    task = do_create_task(title="Summarize report")
    do_complete_task(task["id"], handoff="Report summary is ready; no user action needed.")

    with SessionLocal() as s:
        assert (
            latest_task_handoff(s, task["chat_session_id"])
            == "Report summary is ready; no user action needed."
        )
        assert load_session_as_ui_messages(s, task["chat_session_id"]) == []


@pytest.mark.usefixtures("_test_db")
def test_reassign_to_user_does_not_auto_post_to_main():
    from app.chat.models import Message
    from app.chat.service import get_or_create_main_session
    from app.db import SessionLocal

    task = do_create_task(title="research X")
    do_reassign_task(task["id"], assignee="user", handoff="needs user input")

    with SessionLocal() as s:
        main = get_or_create_main_session(s)
        msgs = s.query(Message).filter(Message.session_id == main.id).all()
    assert msgs == []


@pytest.mark.usefixtures("_test_db")
def test_reassign_to_assistant_does_not_post():
    from app.chat.models import Message
    from app.chat.service import get_or_create_main_session
    from app.db import SessionLocal

    task = do_create_task(title="x", assignee="user")
    do_reassign_task(task["id"], assignee="assistant", handoff="assistant should continue")

    with SessionLocal() as s:
        main = get_or_create_main_session(s)
        msgs = s.query(Message).filter(Message.session_id == main.id).all()
    assert msgs == []


@pytest.mark.usefixtures("_test_db")
def test_compute_kind_combinations():
    from datetime import datetime, timedelta

    from app.tasks.schemas import compute_kind

    future = datetime.utcnow() + timedelta(days=1)

    # User side
    assert compute_kind("user", None, None, None) == "todo"
    assert compute_kind("user", future, None, None) == "scheduled-todo"
    assert compute_kind("user", None, future, None) == "deadline"
    # due_at wins over do_at on user side (deadline framing).
    assert compute_kind("user", future, future, None) == "deadline"

    # Assistant side
    assert compute_kind("assistant", None, None, None) == "job"
    assert compute_kind("assistant", future, None, None) == "scheduled-job"
    assert compute_kind("assistant", None, None, "day") == "routine"
    # Routine wins even with a do_at (do_at anchors first run).
    assert compute_kind("assistant", future, None, "week") == "routine"


@pytest.mark.usefixtures("_test_db")
def test_do_create_task_accepts_due_at():
    from datetime import datetime

    out = do_create_task(title="Letter", assignee="user", due_at=datetime(2099, 6, 1, 17, 0))
    assert out["due_at"].startswith("2099-06-01T17:00")
    assert out["kind"] == "deadline"


@pytest.mark.usefixtures("_test_db")
def test_do_get_task_returns_full_detail():
    created = do_create_task(title="Detailed", description="notes")
    out = do_get_task(created["id"])
    # Full TaskRead surface — including fields stripped from list_tasks
    # summaries (created_at, updated_at, completed_at).
    assert out["id"] == created["id"]
    assert out["title"] == "Detailed"
    assert out["description"] == "notes"
    assert "created_at" in out
    assert "updated_at" in out
    assert "completed_at" in out


@pytest.mark.usefixtures("_test_db")
def test_do_get_task_unknown_returns_error():
    out = do_get_task(9999)
    assert "error" in out


@pytest.mark.usefixtures("_test_db")
def test_do_list_tasks_includes_last_activity_at():
    created = do_create_task(title="Active")
    out = do_list_tasks()
    [row] = [t for t in out["tasks"] if t["id"] == created["id"]]
    assert "last_activity_at" in row
    # Until any chat message lands, activity == updated_at.
    assert row["last_activity_at"] is not None
    # List rows omit `description` to stay compact; get_task has it.
    assert "description" not in row


@pytest.mark.usefixtures("_test_db")
def test_do_list_tasks_filters_by_title_substring():
    do_create_task(title="Weekly reflection")
    do_create_task(title="Plan trip")
    out = do_list_tasks(title="reflection")
    assert [t["title"] for t in out["tasks"]] == ["Weekly reflection"]
    # Case-insensitive.
    out_upper = do_list_tasks(title="REFLECT")
    assert [t["title"] for t in out_upper["tasks"]] == ["Weekly reflection"]


@pytest.mark.usefixtures("_test_db")
def test_do_reschedule_task_sets_do_at():
    task = do_create_task(title="Park me")
    future = datetime.utcnow() + timedelta(hours=2)
    out = do_reschedule_task(task["id"], do_at=future, handoff="wait until later")
    assert out["id"] == task["id"]
    assert out["do_at"] is not None and out["do_at"].startswith(
        future.replace(microsecond=0).isoformat()[:13]
    )


@pytest.mark.usefixtures("_test_db")
def test_do_reschedule_task_does_not_auto_post_to_main():
    from app.chat.models import Message
    from app.chat.service import get_or_create_main_session
    from app.db import SessionLocal

    task = do_create_task(title="Wait first")
    future = datetime.utcnow() + timedelta(hours=1)
    do_reschedule_task(task["id"], do_at=future, handoff="deferred")

    with SessionLocal() as s:
        main = get_or_create_main_session(s)
        msgs = s.query(Message).filter(Message.session_id == main.id).all()
    assert msgs == []


@pytest.mark.usefixtures("_test_db")
def test_do_reschedule_task_unknown_returns_error():
    future = datetime.utcnow() + timedelta(hours=1)
    out = do_reschedule_task(9999, do_at=future, handoff="missing")
    assert "error" in out


@pytest.mark.usefixtures("_test_db")
def test_do_reschedule_task_rejects_past_do_at():
    task = do_create_task(title="No time travel")
    past = datetime.utcnow() - timedelta(hours=1)
    out = do_reschedule_task(task["id"], do_at=past, handoff="too early")
    assert "error" in out


@pytest.mark.usefixtures("_test_db")
def test_do_update_task_changes_description_and_title():
    task = do_create_task(title="Old title", description="old desc")
    out = do_update_task(task["id"], title="New title", description="new desc")
    assert out["title"] == "New title"
    assert out["description"] == "new desc"
    # Persisted.
    fetched = do_get_task(task["id"])
    assert fetched["title"] == "New title"
    assert fetched["description"] == "new desc"


@pytest.mark.usefixtures("_test_db")
def test_do_update_task_partial_update_leaves_other_fields():
    task = do_create_task(title="Keep", description="keep me")
    do_update_task(task["id"], description="changed")
    fetched = do_get_task(task["id"])
    assert fetched["title"] == "Keep"
    assert fetched["description"] == "changed"


@pytest.mark.usefixtures("_test_db")
def test_do_update_task_updates_schedule_and_recurrence():
    task = do_create_task(title="Reschedule via update")
    future = datetime(2099, 7, 1, 9, 0)
    out = do_update_task(
        task["id"],
        do_at=future,
        due_at=datetime(2099, 7, 2, 9, 0),
        interval_unit="week",
        interval_count=2,
    )
    assert out["do_at"].startswith("2099-07-01T09:00")
    assert out["due_at"].startswith("2099-07-02T09:00")
    assert out["interval_unit"] == "week"
    assert out["interval_count"] == 2
    # interval_unit + assistant assignee → kind flips to routine.
    assert out["kind"] == "routine"


@pytest.mark.usefixtures("_test_db")
def test_update_task_tool_kwargs_can_clear_nullable_fields():
    kwargs = _update_task_tool_kwargs(
        clear_description=True,
        clear_do_at=True,
        clear_due_at=True,
        clear_recurrence=True,
    )

    assert kwargs == {
        "description": None,
        "do_at": None,
        "due_at": None,
        "interval_unit": None,
        "interval_count": None,
    }


@pytest.mark.usefixtures("_test_db")
def test_do_update_task_clears_schedule_description_and_recurrence():
    task = do_create_task(
        title="Clear me",
        description="details",
        do_at=datetime(2099, 7, 1, 9, 0),
        due_at=datetime(2099, 7, 2, 9, 0),
        interval_unit="week",
        interval_count=2,
    )

    out = do_update_task(
        task["id"],
        **_update_task_tool_kwargs(
            clear_description=True,
            clear_do_at=True,
            clear_due_at=True,
            clear_recurrence=True,
        ),
    )

    assert out["description"] is None
    assert out["do_at"] is None
    assert out["due_at"] is None
    assert out["interval_unit"] is None
    assert out["interval_count"] is None


@pytest.mark.usefixtures("_test_db")
def test_do_update_task_can_reassign_to_assistant_and_schedule_wake(monkeypatch):
    scheduled: list[int] = []

    def fake_schedule_wake(session_id: int) -> None:
        scheduled.append(session_id)

    monkeypatch.setattr("app.chat.runner.schedule_wake", fake_schedule_wake)

    task = do_create_task(title="Continue from main", assignee="user")
    out = do_update_task(task["id"], assignee="assistant")

    assert out["assignee"] == "assistant"
    assert out["state"] == "running"
    assert scheduled == [task["chat_session_id"]]


@pytest.mark.usefixtures("_test_db")
def test_do_update_task_can_mark_done_and_reopen():
    task = do_create_task(title="Toggle done", assignee="user")

    done = do_update_task(task["id"], is_done=True)
    assert done["is_done"] is True
    assert done["state"] == "done"

    reopened = do_update_task(task["id"], is_done=False)
    assert reopened["is_done"] is False
    assert reopened["state"] == "yours"


@pytest.mark.usefixtures("_test_db")
def test_do_update_task_unknown_returns_error():
    out = do_update_task(9999, title="nope")
    assert "error" in out


@pytest.mark.usefixtures("_test_db")
def test_do_update_task_no_fields_returns_error():
    task = do_create_task(title="needs a field")
    out = do_update_task(task["id"])
    assert "error" in out


@pytest.mark.usefixtures("_test_db")
def test_do_update_task_half_cleared_interval_returns_error():
    task = do_create_task(title="Recurring", interval_unit="day", interval_count=1)
    # Setting only interval_unit → schema validator rejects.
    out = do_update_task(task["id"], interval_unit="week")
    assert "error" in out


@pytest.mark.usefixtures("_test_db")
def test_do_update_task_does_not_post_to_main_chat():
    """No task-tool path posts to main chat anymore — that's the
    main-chat handoff's job. Plain edits least of all."""
    from app.chat.models import Message
    from app.chat.service import get_or_create_main_session
    from app.db import SessionLocal

    task = do_create_task(title="quiet edit")
    do_update_task(task["id"], description="new info")

    with SessionLocal() as s:
        main = get_or_create_main_session(s)
        msgs = s.query(Message).filter(Message.session_id == main.id).all()
    assert msgs == []


@pytest.mark.usefixtures("_test_db")
def test_do_list_tasks_filters_by_since():
    old = do_create_task(title="Old")
    new = do_create_task(title="New")
    # Anything in the far future filters everything out.
    far_future = datetime.utcnow() + timedelta(days=1)
    assert do_list_tasks(since=far_future)["tasks"] == []
    # Anything in the far past keeps everything.
    far_past = datetime.utcnow() - timedelta(days=1)
    titles_past = {t["title"] for t in do_list_tasks(since=far_past)["tasks"]}
    assert {"Old", "New"}.issubset(titles_past)
    # Without `since`, we get everything.
    assert {t["id"] for t in do_list_tasks()["tasks"]} >= {old["id"], new["id"]}


@pytest.mark.usefixtures("_test_db")
def test_do_delete_task_drops_task_and_chat():
    """Deleting via the agent tool removes the task, its chat session,
    and any messages persisted in that chat — no orphaned rows."""
    from app.db import SessionLocal

    task = do_create_task(title="To remove")
    chat_id = task["chat_session_id"]

    with SessionLocal() as s:
        s.add(
            Message(
                session_id=chat_id,
                kind="response",
                parts_json={"parts": [{"part_kind": "text", "content": "hi"}]},
            )
        )
        s.commit()

    out = do_delete_task(task["id"])
    assert out == {"deleted": True, "task_id": task["id"]}

    # Task gone.
    assert do_get_task(task["id"]) == {"error": "task not found", "task_id": task["id"]}

    # Chat session and its messages cleaned up too.
    with SessionLocal() as s:
        assert s.get(ChatSession, chat_id) is None
        assert s.query(Message).filter(Message.session_id == chat_id).count() == 0


@pytest.mark.usefixtures("_test_db")
def test_do_delete_task_unknown_returns_error():
    out = do_delete_task(9999)
    assert "error" in out
    assert out["task_id"] == 9999


@pytest.mark.usefixtures("_test_db")
def test_do_create_task_accepts_offset_aware_do_at():
    from datetime import UTC

    out = do_create_task(
        title="Aware scheduled task",
        assignee="assistant",
        do_at=datetime(2099, 4, 27, 14, 30, tzinfo=UTC),
    )

    assert out["state"] == "up_next"
    assert out["do_at"].startswith("2099-04-27T14:30")


@pytest.mark.usefixtures("_test_db")
def test_do_list_tasks_since_accepts_offset_aware_datetime():
    """Regression: the daily Collect improvement items routine passed an
    ISO timestamp with a `Z` suffix, which pydantic-ai parses as a
    timezone-aware datetime. Comparing it against the naive UTC
    `last_activity_at` from the DB used to crash with
    `can't compare offset-naive and offset-aware datetimes`."""
    from datetime import UTC

    old = do_create_task(title="Old")
    new = do_create_task(title="New")

    far_future_aware = datetime.now(UTC) + timedelta(days=1)
    far_past_aware = datetime.now(UTC) - timedelta(days=1)

    # Aware `since` must not crash and must filter consistently with
    # the naive-UTC interpretation the DB columns store.
    assert do_list_tasks(since=far_future_aware)["tasks"] == []
    titles_past = {t["title"] for t in do_list_tasks(since=far_past_aware)["tasks"]}
    assert {"Old", "New"}.issubset(titles_past)
    assert {t["id"] for t in do_list_tasks()["tasks"]} >= {old["id"], new["id"]}


@pytest.mark.usefixtures("_test_db")
def test_do_reschedule_task_accepts_offset_aware_do_at():
    from datetime import UTC

    task = do_create_task(title="Aware reschedule", assignee="assistant")
    future = datetime(2099, 4, 27, 14, 30, tzinfo=UTC)

    out = do_reschedule_task(task["id"], do_at=future, handoff="aware defer")

    assert "error" not in out
    assert out["do_at"].startswith("2099-04-27T14:30")
