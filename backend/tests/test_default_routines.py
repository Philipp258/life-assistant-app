"""Default assistant routines, formerly seed migrations, now seeded at
boot by `ensure_default_routines` (called from the FastAPI lifespan).

Covers the invariants the old seed migrations + their dedicated tests
guaranteed: every routine exists exactly once, idempotent re-runs,
the 1:1 chat-session invariant, brief parity, and no boot-time wake.
"""

from __future__ import annotations

from sqlalchemy import select

from app.chat.models import ChatSession
from app.chat.runner import should_start_task
from app.defaults.models import SeededDefault
from app.datetime_utils import utc_now
from app.tasks.default_routines import (
    COLLECT_BRIEF,
    COLLECT_TITLE,
    CONSOLIDATION_BRIEF,
    CONSOLIDATION_TITLE,
    DEFAULT_ROUTINES,
    DISK_SPACE_BRIEF,
    DISK_SPACE_TITLE,
    PROCESS_BRIEF,
    PROCESS_TITLE,
    TASK_LOG_MAINTENANCE_BRIEF,
    ensure_default_routines,
)
from app.tasks.models import Task

_ALL_TITLES = {spec.title for spec in DEFAULT_ROUTINES}


def test_seeds_every_routine_once(_test_db):
    with _test_db() as db:
        created = ensure_default_routines(db)
        assert set(created) == _ALL_TITLES

        tasks = db.scalars(select(Task)).all()
        assert {t.title for t in tasks} == _ALL_TITLES

        by_title = {t.title: t for t in tasks}
        for spec in DEFAULT_ROUTINES:
            task = by_title[spec.title]
            assert task.assignee == "assistant"
            assert task.is_done is False
            assert task.interval_unit == spec.interval_unit
            assert task.interval_count == spec.interval_count
            assert task.description == spec.description
            # Future do_at: a routine must not wake the instant it's seeded.
            assert task.do_at is not None and task.do_at > utc_now()

            # 1:1 chat session, both back-pointers wired (NOT NULL + CASCADE).
            chat = db.get(ChatSession, task.chat_session_id)
            assert chat is not None and chat.task_id == task.id


def test_idempotent_second_run_is_a_noop(_test_db):
    with _test_db() as db:
        ensure_default_routines(db)
        again = ensure_default_routines(db)
        assert again == []
        assert len(db.scalars(select(Task)).all()) == len(DEFAULT_ROUTINES)


def test_skips_routine_whose_title_already_exists(_test_db):
    """Pre-existing same-title task is adopted into the stable-key ledger.

    The row is left untouched — not duplicated, description not overwritten.
    """
    from app.tasks.schemas import TaskCreate
    from app.tasks.service import create_task

    with _test_db() as db:
        create_task(
            db,
            TaskCreate(
                title=CONSOLIDATION_TITLE,
                description="hand-edited brief on the live box",
                assignee="assistant",
            ),
        )

        created = ensure_default_routines(db)

        assert CONSOLIDATION_TITLE not in created
        assert set(created) == _ALL_TITLES - {CONSOLIDATION_TITLE}
        rows = db.scalars(select(Task).where(Task.title == CONSOLIDATION_TITLE)).all()
        assert len(rows) == 1
        assert rows[0].description == "hand-edited brief on the live box"
        ledger = db.get(SeededDefault, ("task_routine", "daily-consolidation"))
        assert ledger is not None
        assert ledger.target_id == rows[0].id


def test_drifted_collect_title_is_adopted_without_duplicate(_test_db):
    from app.tasks.schemas import TaskCreate
    from app.tasks.service import create_task

    with _test_db() as db:
        original = create_task(
            db,
            TaskCreate(
                title="Collect improvement opportunities",
                description="evolved live brief",
                assignee="assistant",
            ),
        )

        created = ensure_default_routines(db)

        assert COLLECT_TITLE not in created
        assert set(created) == _ALL_TITLES - {COLLECT_TITLE}
        collectish = db.scalars(
            select(Task).where(Task.title.in_([COLLECT_TITLE, "Collect improvement opportunities"]))
        ).all()
        assert [(t.id, t.title, t.description) for t in collectish] == [
            (original.id, "Collect improvement opportunities", "evolved live brief")
        ]
        ledger = db.get(SeededDefault, ("task_routine", "collect-improvement-items"))
        assert ledger is not None
        assert ledger.target_id == original.id


def test_seeded_default_is_not_resurrected_after_delete(_test_db):
    with _test_db() as db:
        ensure_default_routines(db)
        collect = db.scalars(select(Task).where(Task.title == COLLECT_TITLE)).one()
        db.delete(collect)
        db.commit()

        created = ensure_default_routines(db)

        assert created == []
        assert db.scalar(select(Task.id).where(Task.title == COLLECT_TITLE)) is None
        assert db.get(SeededDefault, ("task_routine", "collect-improvement-items")) is not None


def test_new_default_added_later_is_seeded_once_by_key(_test_db, monkeypatch):
    from app.tasks import default_routines as defaults

    with _test_db() as db:
        ensure_default_routines(db)
        extra = defaults.RoutineSpec(
            key="new-test-routine",
            title="New test routine",
            description="seed me once",
            interval_unit="day",
            interval_count=1,
            schedule=lambda now: defaults._tomorrow_at(now, hour=6),
        )
        monkeypatch.setattr(defaults, "DEFAULT_ROUTINES", (*defaults.DEFAULT_ROUTINES, extra))

        created = ensure_default_routines(db)
        again = ensure_default_routines(db)

        assert created == ["New test routine"]
        assert again == []
        assert len(db.scalars(select(Task).where(Task.title == "New test routine")).all()) == 1
        assert db.get(SeededDefault, ("task_routine", "new-test-routine")) is not None


def test_seeded_default_is_immutable_when_code_spec_changes(_test_db, monkeypatch):
    from app.tasks import default_routines as defaults

    with _test_db() as db:
        ensure_default_routines(db)
        original = db.scalars(select(Task).where(Task.title == CONSOLIDATION_TITLE)).one()
        changed = defaults.RoutineSpec(
            key="daily-consolidation",
            title="Renamed consolidation",
            description="new code brief",
            interval_unit="week",
            interval_count=1,
            schedule=lambda now: defaults._next_weekday_at(now, weekday=0, hour=6),
        )
        monkeypatch.setattr(
            defaults,
            "DEFAULT_ROUTINES",
            tuple(
                changed if spec.key == "daily-consolidation" else spec
                for spec in defaults.DEFAULT_ROUTINES
            ),
        )

        created = ensure_default_routines(db)

        db.refresh(original)
        assert created == []
        assert original.title == CONSOLIDATION_TITLE
        assert original.description == CONSOLIDATION_BRIEF
        assert original.interval_unit == "day"
        assert db.scalar(select(Task.id).where(Task.title == "Renamed consolidation")) is None


def test_seeded_routines_do_not_wake_at_boot(_test_db):
    with _test_db() as db:
        ensure_default_routines(db)
        for task in db.scalars(select(Task)).all():
            assert should_start_task(task) is False


def test_disk_space_inbox_label_is_optional(_test_db):
    """`_resolve_labels` raises on an unknown slug; the old disk-space
    seed only attached `inbox` when it existed. No label -> no crash."""
    with _test_db() as db:
        ensure_default_routines(db)
        disk = db.scalars(select(Task).where(Task.title == DISK_SPACE_TITLE)).one()
        assert [label.slug for label in disk.labels] == []


def test_disk_space_gets_inbox_label_when_present(_test_db):
    from app.labels.models import Label

    with _test_db() as db:
        db.add(Label(slug="inbox", name="Inbox"))
        db.commit()

        ensure_default_routines(db)

        disk = db.scalars(select(Task).where(Task.title == DISK_SPACE_TITLE)).one()
        assert [label.slug for label in disk.labels] == ["inbox"]


def test_brief_constants_are_the_final_seed_text(_test_db):
    """Guard the core routine-brief invariants that old migrations used to cover."""
    assert CONSOLIDATION_TITLE == "Daily consolidation"
    assert "harvest durable bits" in CONSOLIDATION_BRIEF
    assert COLLECT_TITLE == "Collect improvement items"
    assert "Each item becomes its own task" in COLLECT_BRIEF
    assert "let the task triage" in COLLECT_BRIEF
    assert PROCESS_TITLE == "Process improvement items"
    assert "Context budget is a hard constraint" in PROCESS_BRIEF
    assert "Do not run broad repo or chat-history searches" in PROCESS_BRIEF


def test_briefs_do_not_hardcode_interval_windows():
    """Briefs must talk in relative terms; the Run context block carries the cadence.

    Hardcoded "once a day"/"last 24 hours"/"one week" phrasing drifts the
    moment the user edits the routine's interval. Window definitions live
    in the runtime-injected Run context block (see
    `app.chat.runner.messages._run_context_block`).
    """
    forbidden = (
        "once a day",
        "once a week",
        "last 24 hours",
        "one day ago",
        "one week",
        "yesterday",
        "tomorrow",
        "next week",
    )
    for brief in (
        CONSOLIDATION_BRIEF,
        COLLECT_BRIEF,
        PROCESS_BRIEF,
        DISK_SPACE_BRIEF,
        TASK_LOG_MAINTENANCE_BRIEF,
    ):
        lower = brief.lower()
        for phrase in forbidden:
            assert phrase not in lower, f"brief leaks {phrase!r}: {brief[:80]}…"
