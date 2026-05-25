"""The squashed baseline must no-op on an already-provisioned DB.

Schema parity vs. the old 43-migration chain was verified once at
squash time by diffing `alembic upgrade head` output against the old
chain (whitespace-only difference). That's a one-shot proof, not an
ongoing invariant — `0001_baseline.py` is static DDL with no chain to
drift — so no golden snapshot is persisted. What stays is the
defensive guard: the live box's `alembic_version` points at a
now-deleted revision, so it must be stamped onto the baseline, and a
subsequent `alembic upgrade head` must not try to recreate its schema.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

_BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture()
def alembic_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, str]:
    db_path = tmp_path / "baseline.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    # env.py reads the already-imported settings singleton and re-sets the
    # Alembic URL from it, so patch settings too — otherwise the migration
    # runs against the real data DB.
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", url, raising=True)
    cfg = Config(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg, str(db_path)


def test_upgrade_is_noop_on_already_provisioned_db(alembic_cfg):
    """A DB that already has `tasks` (the live box at the old head) is
    left untouched by the baseline itself — it only records the
    revision. Targets 0001_baseline specifically: migrations stacked on
    top run real data transforms against the real schema, not this
    minimal stand-in, so they're out of scope here."""
    cfg, db_path = alembic_cfg

    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, sentinel TEXT)")
    con.execute("INSERT INTO tasks (sentinel) VALUES ('preexisting')")
    con.commit()
    con.close()

    command.upgrade(cfg, "0001_baseline")

    con = sqlite3.connect(db_path)
    try:
        tables = {
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        # Baseline create was skipped: no other app tables, sentinel row intact.
        assert "labels" not in tables
        assert "sessions" not in tables
        assert con.execute("SELECT sentinel FROM tasks").fetchone()[0] == "preexisting"
        version = con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert version == "0001_baseline"
    finally:
        con.close()
