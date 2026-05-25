"""Bootstrap prompt carries a Run context block for recurring routines.

Decouples brief text from the live cadence: briefs talk in relative
terms ("since the previous run"), the runner injects the live cadence
and previous-completion timestamp at bootstrap time.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.chat.models import ChatSession
from app.chat.runner.messages import (
    _bootstrap_prompt,
    _build_bootstrap_request,
    _format_cadence,
    _run_context_block,
)
from app.datetime_utils import utc_now
from app.tasks.models import Task
from app.tasks.service import previous_completed_sibling


def _make_routine(
    Session,
    *,
    log_line: str = "weekly-reflection",
    interval_unit: str = "week",
    interval_count: int = 1,
    title: str = "Weekly reflection",
) -> tuple[int, int]:
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(
            title=title,
            description="brief body",
            assignee="assistant",
            chat_session_id=chat.id,
            interval_unit=interval_unit,
            interval_count=interval_count,
            task_log_line=log_line,
        )
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        return task.id, chat.id


def test_cadence_formatting():
    assert _format_cadence(1, "day") == "every day"
    assert _format_cadence(1, "week") == "every week"
    assert _format_cadence(2, "week") == "every 2 weeks"
    assert _format_cadence(3, "hour") == "every 3 hours"


def test_recurring_task_first_cycle_block(_test_db):
    Session = _test_db
    task_id, _ = _make_routine(Session)
    with Session() as s:
        task = s.get(Task, task_id)
        block = _run_context_block(task, prev_completed_at=None)
    assert block is not None
    assert "Cadence: every week." in block
    assert "Previous completion: none (first cycle)." in block


def test_recurring_task_with_prev_completion_block(_test_db):
    Session = _test_db
    task_id, _ = _make_routine(Session, interval_unit="day", interval_count=1)
    prev = datetime(2026, 5, 16, 9, 12, 0)
    with Session() as s:
        task = s.get(Task, task_id)
        block = _run_context_block(task, prev_completed_at=prev)
    assert block is not None
    assert "Cadence: every day." in block
    assert "Previous completion: 2026-05-16 09:12 UTC." in block


def test_non_recurring_task_gets_no_block(_test_db):
    Session = _test_db
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(
            title="One-shot",
            assignee="assistant",
            chat_session_id=chat.id,
        )
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        assert _run_context_block(task, prev_completed_at=None) is None


def test_bootstrap_prompt_includes_block_for_recurring(_test_db):
    Session = _test_db
    task_id, _ = _make_routine(Session)
    with Session() as s:
        task = s.get(Task, task_id)
        prompt = _bootstrap_prompt(task, prev_completed_at=None)
    assert "## Run context" in prompt
    assert "Cadence: every week." in prompt
    # Notes still present.
    assert "Notes: brief body" in prompt
    # Closing instruction still appended after the block.
    assert prompt.endswith("do not post directly to main chat.")


def test_bootstrap_prompt_omits_block_for_one_shot(_test_db):
    Session = _test_db
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(
            title="One-shot",
            description="x",
            assignee="assistant",
            chat_session_id=chat.id,
        )
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        prompt = _bootstrap_prompt(task, prev_completed_at=None)
    assert "## Run context" not in prompt


def test_build_bootstrap_request_threads_prev_completion(_test_db):
    Session = _test_db
    task_id, _ = _make_routine(Session)
    prev = datetime(2026, 5, 16, 9, 0, 0)
    with Session() as s:
        task = s.get(Task, task_id)
        req = _build_bootstrap_request(task, prev_completed_at=prev)
    content = req.parts[0].content
    assert "Previous completion: 2026-05-16 09:00 UTC." in content


def test_previous_completed_sibling_finds_last_done_on_same_log_line(_test_db):
    Session = _test_db
    with Session() as s:
        # Three chats (old, recent, current) -> three tasks sharing one
        # task_log_line. Two completed (different timestamps), one open.
        c_old = ChatSession(title="old")
        c_recent = ChatSession(title="recent")
        c_cur = ChatSession(title="cur")
        s.add_all([c_old, c_recent, c_cur])
        s.flush()

        old = Task(
            title="Weekly reflection",
            assignee="assistant",
            chat_session_id=c_old.id,
            interval_unit="week",
            interval_count=1,
            task_log_line="weekly-reflection",
            is_done=True,
            completed_at=utc_now() - timedelta(days=14),
        )
        recent = Task(
            title="Weekly reflection",
            assignee="assistant",
            chat_session_id=c_recent.id,
            interval_unit="week",
            interval_count=1,
            task_log_line="weekly-reflection",
            is_done=True,
            completed_at=utc_now() - timedelta(days=7),
        )
        cur = Task(
            title="Weekly reflection",
            assignee="assistant",
            chat_session_id=c_cur.id,
            interval_unit="week",
            interval_count=1,
            task_log_line="weekly-reflection",
        )
        s.add_all([old, recent, cur])
        s.flush()
        c_old.task_id = old.id
        c_recent.task_id = recent.id
        c_cur.task_id = cur.id
        s.commit()
        cur_id = cur.id
        recent_id = recent.id

    with Session() as s:
        cur = s.get(Task, cur_id)
        sibling = previous_completed_sibling(s, cur)
        assert sibling is not None
        assert sibling.id == recent_id


def test_previous_completed_sibling_returns_none_for_one_shot(_test_db):
    Session = _test_db
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(
            title="one-off",
            assignee="assistant",
            chat_session_id=chat.id,
        )
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        assert previous_completed_sibling(s, task) is None
