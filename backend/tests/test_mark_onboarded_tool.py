"""`mark_onboarded` tool flips `users.onboarded_at` once identity is set."""

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
    """Singleton user mid-onboarding: onboarded_at nulled, identity cleared."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.settings.models import AppSetting
    from app.users.models import User

    with SessionLocal() as db:
        user = db.scalars(select(User)).first()
        user.onboarded_at = None
        db.query(AppSetting).filter(
            AppSetting.key.in_(["assistant_name", "user_name"])
        ).delete()
        db.commit()
        return user.id


def test_mark_onboarded_refuses_when_identity_incomplete(seeded_user):
    from app.agent.tools.onboarding import do_mark_onboarded
    from app.db import SessionLocal
    from app.users.models import User

    result = do_mark_onboarded()

    assert result == {"ok": False, "error": "identity_incomplete"}
    with SessionLocal() as db:
        assert db.get(User, seeded_user).onboarded_at is None


def test_mark_onboarded_succeeds_once_both_names_set(seeded_user):
    from app.agent.tools.onboarding import (
        do_mark_onboarded,
        do_set_assistant_name,
        do_set_user_name,
    )
    from app.db import SessionLocal
    from app.users.models import User

    do_set_assistant_name("Atlas")
    do_set_user_name("Phil")
    result = do_mark_onboarded()

    assert result == {"ok": True, "already_onboarded": False}
    with SessionLocal() as db:
        assert db.get(User, seeded_user).onboarded_at is not None


def test_mark_onboarded_idempotent(seeded_user):
    from app.agent.tools.onboarding import (
        do_mark_onboarded,
        do_set_assistant_name,
        do_set_user_name,
    )
    from app.db import SessionLocal
    from app.users.models import User

    do_set_assistant_name("Atlas")
    do_set_user_name("Phil")
    do_mark_onboarded()
    with SessionLocal() as db:
        first_stamp = db.get(User, seeded_user).onboarded_at

    second = do_mark_onboarded()

    assert second == {"ok": True, "already_onboarded": True}
    with SessionLocal() as db:
        assert db.get(User, seeded_user).onboarded_at == first_stamp


def test_mark_onboarded_switches_prompt_branch(seeded_user, core_root):
    from app.agent import build_system_prompt
    from app.agent.tools.onboarding import (
        do_mark_onboarded,
        do_set_assistant_name,
        do_set_user_name,
    )
    from app.knowledge import core as core_mod

    core_mod.seed_if_missing()

    pre = build_system_prompt(None)
    assert "brand-new assistant" in pre

    do_set_assistant_name("Atlas")
    do_set_user_name("Phil")
    do_mark_onboarded()

    post = build_system_prompt(None)
    assert "## Identity" in post
    assert "Your name is Atlas." in post
    assert "You are talking with Phil." in post
    assert "brand-new assistant" not in post
