"""Stable task-log identity for recurring assistant routines."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.tasks import service as tasks_service
from app.tasks.default_routines import (
    DEFAULT_ROUTINES,
    TASK_LOG_MAINTENANCE_BRIEF,
    TASK_LOG_MAINTENANCE_TITLE,
    ensure_default_routines,
)
from app.tasks.models import Task
from app.tasks.schemas import TaskCreate, TaskUpdate
from app.tasks.task_log import (
    allocate_task_log_line,
    is_recurring_assistant_task,
    should_expose_task_log,
    slugify_title,
    task_log_path,
)


def test_slugify_title_lowercases_dashes_and_strips_punctuation():
    assert slugify_title("Weekly reflection") == "weekly-reflection"
    assert slugify_title("  Daily  consolidation!  ") == "daily-consolidation"
    assert slugify_title("Task log maintenance") == "task-log-maintenance"


def test_slugify_title_empty_falls_back():
    assert slugify_title("   !!!  ") == "routine"


def test_task_log_path_lives_under_task_log_folder():
    assert task_log_path("weekly-reflection") == "Task Log/weekly-reflection.md"


@pytest.mark.parametrize(
    "assignee,interval_unit,interval_count,expected",
    [
        ("assistant", "day", 1, True),
        ("assistant", "week", 2, True),
        ("assistant", None, None, False),  # one-shot assistant job
        ("user", "day", 1, False),  # user-owned (UI shouldn't allow this anyway)
        ("user", None, None, False),
    ],
)
def test_is_recurring_assistant_task(assignee, interval_unit, interval_count, expected):
    assert (
        is_recurring_assistant_task(
            assignee=assignee,
            interval_unit=interval_unit,
            interval_count=interval_count,
        )
        is expected
    )


def test_should_expose_task_log_when_identity_exists():
    assert should_expose_task_log(task_log_line="daily-x")
    assert not should_expose_task_log(task_log_line=None)


def test_create_recurring_assistant_task_gets_stable_log_line(_test_db):
    with _test_db() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(
                title="Brew the daily tea",
                assignee="assistant",
                interval_unit="day",
                interval_count=1,
            ),
        )
        assert task.task_log_line == "brew-the-daily-tea"


def test_create_non_recurring_assistant_task_has_no_log_line(_test_db):
    with _test_db() as db:
        one_shot = tasks_service.create_task(
            db,
            TaskCreate(title="Ping me later", assignee="assistant"),
        )
        user_task = tasks_service.create_task(
            db,
            TaskCreate(title="Pay rent", assignee="user"),
        )
        assert one_shot.task_log_line is None
        assert user_task.task_log_line is None


def test_recurring_creation_resolves_slug_collision(_test_db):
    with _test_db() as db:
        first = tasks_service.create_task(
            db,
            TaskCreate(
                title="Quick check",
                assignee="assistant",
                interval_unit="day",
                interval_count=1,
            ),
        )
        second = tasks_service.create_task(
            db,
            TaskCreate(
                title="Quick check",
                assignee="assistant",
                interval_unit="week",
                interval_count=1,
            ),
        )
        assert first.task_log_line == "quick-check"
        assert second.task_log_line == "quick-check-2"


def test_recurrence_spawn_preserves_log_line(_test_db):
    with _test_db() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(
                title="Daily X",
                assignee="assistant",
                interval_unit="day",
                interval_count=1,
                do_at=datetime.now(UTC) - timedelta(minutes=1),
            ),
        )
        original_line = task.task_log_line
        assert original_line == "daily-x"

        tasks_service.update_task(db, task.id, TaskUpdate(is_done=True))

        rows = db.scalars(select(Task).where(Task.title == "Daily X").order_by(Task.id)).all()
        assert len(rows) == 2
        # New cycle row inherits identity — even though it's a fresh row
        # with a fresh chat session, the log file stays the same.
        assert rows[1].id != task.id
        assert rows[1].chat_session_id != task.chat_session_id
        assert rows[1].task_log_line == original_line


def test_title_edit_does_not_repoint_log_line(_test_db):
    with _test_db() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(
                title="Old name",
                assignee="assistant",
                interval_unit="day",
                interval_count=1,
            ),
        )
        original_line = task.task_log_line
        assert original_line == "old-name"

        updated = tasks_service.update_task(db, task.id, TaskUpdate(title="New name"))
        assert updated is not None
        assert updated.task_log_line == original_line


def test_update_into_recurring_assigns_log_line(_test_db):
    with _test_db() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(title="Will become recurring", assignee="assistant"),
        )
        assert task.task_log_line is None

        updated = tasks_service.update_task(
            db,
            task.id,
            TaskUpdate(interval_unit="day", interval_count=1),
        )
        assert updated is not None
        assert updated.task_log_line == "will-become-recurring"


def test_clearing_recurrence_drops_log_line(_test_db):
    with _test_db() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(
                title="Temporary routine",
                assignee="assistant",
                interval_unit="day",
                interval_count=1,
            ),
        )
        assert task.task_log_line == "temporary-routine"

        updated = tasks_service.update_task(
            db,
            task.id,
            TaskUpdate(interval_unit=None, interval_count=None),
        )
        assert updated is not None
        assert updated.task_log_line is None


def test_default_routines_all_get_log_lines(_test_db):
    with _test_db() as db:
        ensure_default_routines(db)
        tasks = db.scalars(select(Task)).all()
        # Every default routine is recurring assistant — each must have
        # a non-null log line.
        assert all(t.task_log_line for t in tasks)
        # Spec keys are derived from titles by the same slugify rule, so
        # the seeded log lines match each spec's key.
        by_title = {t.title: t for t in tasks}
        for spec in DEFAULT_ROUTINES:
            assert by_title[spec.title].task_log_line == slugify_title(spec.title)


def test_allocate_excludes_self_when_recomputing(_test_db):
    with _test_db() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(
                title="Self check",
                assignee="assistant",
                interval_unit="day",
                interval_count=1,
            ),
        )
        # If we re-allocate while excluding the same task, we should
        # get the same base slug back (no spurious suffix).
        again = allocate_task_log_line(db, title="Self check", exclude_task_id=task.id)
        assert again == "self-check"


def test_task_log_maintenance_routine_exists():
    titles = {spec.title for spec in DEFAULT_ROUTINES}
    assert TASK_LOG_MAINTENANCE_TITLE in titles


def test_task_log_maintenance_brief_compresses_history_not_rules():
    assert "preserve enough history" in TASK_LOG_MAINTENANCE_BRIEF
    assert "narrative summary" in TASK_LOG_MAINTENANCE_BRIEF
    assert "Do not convert the log into rules" in TASK_LOG_MAINTENANCE_BRIEF
    assert "Keep full detail for recent entries" in TASK_LOG_MAINTENANCE_BRIEF
    assert "deprecate stale signal" in TASK_LOG_MAINTENANCE_BRIEF
    assert "Do not invent outcomes" in TASK_LOG_MAINTENANCE_BRIEF
    assert "Lessons" not in TASK_LOG_MAINTENANCE_BRIEF


def test_task_chat_prompt_includes_task_log_section_for_recurring_routine(_test_db):
    from app.agent import build_system_prompt

    with _test_db() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(
                title="Weekly thing",
                assignee="assistant",
                interval_unit="week",
                interval_count=1,
            ),
        )
        sid = task.chat_session_id

    prompt = build_system_prompt(sid)
    assert "## Task log" in prompt
    assert "Task Log/weekly-thing.md" in prompt
    assert "Always read it at the start of the cycle" in prompt


def test_task_chat_prompt_omits_task_log_section_for_one_shot(_test_db):
    from app.agent import build_system_prompt

    with _test_db() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(title="One-shot job", assignee="assistant"),
        )
        sid = task.chat_session_id

    prompt = build_system_prompt(sid)
    assert "## Task log" not in prompt
    assert "task_log:" not in prompt


def test_task_chat_prompt_omits_task_log_after_recurrence_cleared(_test_db):
    from app.agent import build_system_prompt

    with _test_db() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(
                title="Routine turned one-shot",
                assignee="assistant",
                interval_unit="week",
                interval_count=1,
            ),
        )
        updated = tasks_service.update_task(
            db,
            task.id,
            TaskUpdate(interval_unit=None, interval_count=None),
        )
        assert updated is not None
        sid = updated.chat_session_id

    prompt = build_system_prompt(sid)
    assert "## Task log" not in prompt
    assert "task_log:" not in prompt


def test_task_to_read_keeps_task_log_line_internal(_test_db):
    from app.tasks.schemas import task_to_read

    with _test_db() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(
                title="Routine X",
                assignee="assistant",
                interval_unit="day",
                interval_count=1,
            ),
        )
        read = task_to_read(task)
    assert "task_log_line" not in read.model_dump()


def test_agent_get_task_exposes_task_log_path(_test_db):
    from app.agent.tools.tasks import do_get_task

    with _test_db() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(
                title="Routine X",
                assignee="assistant",
                interval_unit="day",
                interval_count=1,
            ),
        )
        task_id = task.id

    out = do_get_task(task_id)
    assert out["task_log"] == "Task Log/routine-x.md"
    assert "task_log_line" not in out
