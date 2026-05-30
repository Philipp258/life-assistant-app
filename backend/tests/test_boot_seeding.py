"""Integration: the FastAPI lifespan seeds default routines + task views.

The harness replaces repo default seeding with a no-op so app-via-client
tests start clean; this test restores the real helper and boots a real
TestClient to prove the lifespan wiring actually runs the seeders. Their
detailed behaviour is covered in test_default_routines /
test_saved_task_views_models.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.saved_task_views.models import SavedTaskView
from app.tasks.default_routines import DEFAULT_ROUTINES
from app.tasks.models import Task

_ALL_TITLES = {spec.title for spec in DEFAULT_ROUTINES}


def test_lifespan_seeds_defaults(_test_db, monkeypatch):
    from app import main as main_mod
    from app.saved_task_views.defaults import ensure_default_saved_views
    from app.tasks.default_routines import ensure_default_routines

    def seed_repo_defaults(db):
        ensure_default_routines(db)
        ensure_default_saved_views(db)

    monkeypatch.setattr(main_mod, "seed_repo_defaults", seed_repo_defaults, raising=True)

    # Entering the context manager runs the lifespan startup.
    with TestClient(main_mod.app):
        pass
    # A second boot must be stable: no duplicate defaults, no churn.
    with TestClient(main_mod.app):
        pass

    with _test_db() as db:
        titles = set(db.scalars(select(Task.title)))
        assert _ALL_TITLES <= titles
        assert len(db.scalars(select(Task)).all()) == len(DEFAULT_ROUTINES)

        views = list(db.scalars(select(SavedTaskView).order_by(SavedTaskView.sort_index)))
        assert [view.name for view in views] == ["Inbox", "Mine", "Assistant"]
        assert [view.filters_json for view in views] == [
            {},
            {"assignee": "user"},
            {"assignee": "assistant"},
        ]
        assert [view.is_default for view in views] == [True, False, False]


def test_lifespan_uses_test_noop_for_clean_client_state(_test_db):
    """conftest's test-only no-op keeps ordinary client tests clean."""
    from app.main import app

    with TestClient(app):
        pass

    with _test_db() as db:
        assert db.scalar(select(Task.id).limit(1)) is None
        assert db.scalar(select(SavedTaskView.id).limit(1)) is None
