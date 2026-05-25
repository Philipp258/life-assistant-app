"""Guard against the dual-head failure that broke self-update on 2026-05-07.

`deploy/update.sh` runs `alembic upgrade head`, which aborts when the
migration graph has more than one head. A merge revision must be added
whenever two branches land in parallel.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


@pytest.fixture()
def alembic_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    backend_root = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "life_assistant.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    # env.py reads the already-imported settings singleton, so patch it in
    # addition to the env var before Alembic loads the migration environment.
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", db_url, raising=True)
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.attributes["db_path"] = db_path
    return cfg


def test_alembic_has_single_head(alembic_cfg: Config) -> None:
    script = ScriptDirectory.from_config(alembic_cfg)
    heads = script.get_heads()
    assert len(heads) == 1, (
        f"Expected exactly one Alembic head, found {len(heads)}: {heads}. "
        "Add a merge revision via `alembic merge -m '...' <head1> <head2>`."
    )


def test_alembic_upgrade_head_succeeds_on_clean_database(alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, "head")


def test_seeded_defaults_migration_preserves_deleted_routines_on_existing_install(
    alembic_cfg: Config,
) -> None:
    command.upgrade(alembic_cfg, "b1f7a4c20d83")

    con = sqlite3.connect(alembic_cfg.attributes["db_path"])
    try:
        con.execute("INSERT INTO sessions (title, kind) VALUES ('Life Assistant', 'main')")
        con.execute("INSERT INTO users (password_hash) VALUES ('x')")
        con.execute(
            """
            INSERT INTO saved_task_views
              (name, icon, filters_json, group_by, sort_index, is_default)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "Today",
                "☀️",
                json.dumps({"due": "today", "statuses": ["open", "scheduled"]}),
                "none",
                0,
                1,
            ),
        )
        con.commit()
    finally:
        con.close()

    command.upgrade(alembic_cfg, "head")

    con = sqlite3.connect(alembic_cfg.attributes["db_path"])
    try:
        rows = con.execute(
            """
            SELECT default_key, target_id
            FROM seeded_defaults
            WHERE default_type = 'task_routine'
            ORDER BY default_key
            """
        ).fetchall()
        assert rows == [
            ("collect-improvement-items", None),
            ("daily-consolidation", None),
            ("process-improvement-items", None),
            ("weekly-disk-space-check", None),
            ("weekly-reflection", None),
        ]

        view = con.execute(
            "SELECT name, icon, filters_json FROM saved_task_views WHERE id = 1"
        ).fetchone()
        assert view[0] == "Tasks"
        assert view[1] is None
        assert json.loads(view[2]) == {}
        assert (
            con.execute(
                "SELECT count(*) FROM seeded_defaults WHERE default_type = 'saved_task_view'"
            ).fetchone()[0]
            == 0
        )
    finally:
        con.close()


def test_task_log_line_backfill_for_existing_recurring_routines(alembic_cfg: Config) -> None:
    """The task-log-line migration backfills slugs onto recurring assistant
    rows that pre-date the column. Other rows stay NULL. Historical cycles
    of the same routine share one readable line, while multiple active
    rows with the same slug still get disambiguated."""
    command.upgrade(alembic_cfg, "2c9f54e0f1a7")

    con = sqlite3.connect(alembic_cfg.attributes["db_path"])
    try:
        con.execute(
            """
            INSERT INTO sessions (id, title, kind) VALUES
              (1, 'one', 'task'),
              (2, 'two', 'task'),
              (3, 'three', 'task'),
              (4, 'four', 'task'),
              (5, 'five', 'task'),
              (6, 'six', 'task'),
              (7, 'seven', 'task')
            """
        )
        # 1) Recurring assistant routine — should slugify by title.
        # 2) Completed predecessor with same slug — same line, because
        #    it is probably a prior cycle of the same routine.
        # 3) One-shot assistant task — should remain NULL.
        # 4) User-owned recurring (unusual but possible) — should
        #    remain NULL.
        # 5,6) Two active rows with the same slug — ambiguous live
        #    routines, so they get distinct suffixes.
        # 7) Completed predecessor for those ambiguous rows — no reliable
        #    lineage, so it is disambiguated with the same active group.
        con.execute(
            """
            INSERT INTO tasks
              (id, title, assignee, chat_session_id, interval_unit, interval_count, is_done)
            VALUES
              (1, 'Weekly Reflection', 'assistant', 1, 'week', 1, 0),
              (2, 'Weekly Reflection!', 'assistant', 2, 'week', 1, 1),
              (3, 'Run once', 'assistant', 3, NULL, NULL, 0),
              (4, 'Buy groceries', 'user', 4, 'week', 1, 0),
              (5, 'Quick check', 'assistant', 5, 'day', 1, 0),
              (6, 'Quick check!', 'assistant', 6, 'day', 1, 0),
              (7, 'Quick check', 'assistant', 7, 'day', 1, 1)
            """
        )
        con.commit()
    finally:
        con.close()

    command.upgrade(alembic_cfg, "head")

    con = sqlite3.connect(alembic_cfg.attributes["db_path"])
    try:
        rows = dict(con.execute("SELECT id, task_log_line FROM tasks ORDER BY id").fetchall())
        assert rows[1] == "weekly-reflection"
        assert rows[2] == "weekly-reflection"
        assert rows[3] is None
        assert rows[4] is None
        assert rows[5] == "quick-check"
        assert rows[6] == "quick-check-2"
        assert rows[7] == "quick-check-3"
    finally:
        con.close()
