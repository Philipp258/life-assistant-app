"""Phase 3: mark_onboarded tool flips users.onboarded_at."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def core_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "core"
    root.mkdir()
    import app.config as config_mod
    from app.knowledge import core as core_mod

    monkeypatch.setattr(config_mod, "CORE_DIR", root, raising=True)
    monkeypatch.setattr(core_mod, "CORE_DIR", root, raising=True)
    return root


@pytest.fixture
def seeded_user(_test_db):
    """Singleton user with onboarded_at nulled out (mid-onboarding)."""
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.users.models import User

    with SessionLocal() as db:
        user = db.scalars(select(User)).first()
        user.onboarded_at = None
        db.commit()
        return user.id


def test_mark_onboarded_sets_timestamp(seeded_user):
    from app.agent.tools.onboarding import do_mark_onboarded
    from app.db import SessionLocal
    from app.users.models import User

    result = do_mark_onboarded()

    assert result == {"ok": True, "already_onboarded": False}
    with SessionLocal() as db:
        user = db.get(User, seeded_user)
        assert user.onboarded_at is not None


def test_mark_onboarded_idempotent(seeded_user):
    from app.agent.tools.onboarding import do_mark_onboarded
    from app.db import SessionLocal
    from app.users.models import User

    do_mark_onboarded()
    with SessionLocal() as db:
        first_stamp = db.get(User, seeded_user).onboarded_at

    second = do_mark_onboarded()

    assert second == {"ok": True, "already_onboarded": True}
    with SessionLocal() as db:
        assert db.get(User, seeded_user).onboarded_at == first_stamp


def test_mark_onboarded_switches_prompt_branch(seeded_user, core_root):
    from app.agent import build_system_prompt
    from app.agent.tools.onboarding import do_mark_onboarded
    from app.knowledge import core as core_mod

    core_mod.seed_if_missing()
    (core_root / "behavior.md").write_text("**Name:** Atlas\n", encoding="utf-8")

    pre = build_system_prompt(None)
    assert "brand-new assistant" in pre

    do_mark_onboarded()

    post = build_system_prompt(None)
    assert "You are Atlas, the assistant inside Life Assistant" in post
    assert "brand-new assistant" not in post
