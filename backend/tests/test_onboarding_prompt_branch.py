"""Phase 3: build_system_prompt branches on the users.onboarded_at flag."""

from __future__ import annotations

from datetime import UTC, datetime
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


def _set_onboarded(user_id: int, when: datetime | None) -> None:
    from app.db import SessionLocal
    from app.users.models import User

    with SessionLocal() as db:
        user = db.get(User, user_id)
        user.onboarded_at = when
        db.commit()


def _make_session(kind: str) -> int:
    from app.chat.models import ChatSession
    from app.db import SessionLocal

    with SessionLocal() as db:
        session = ChatSession(kind=kind, title=f"{kind} chat")
        db.add(session)
        db.commit()
        db.refresh(session)
        return session.id


def test_main_session_uses_onboarding_prompt_when_flag_null(seeded_user, core_root):
    from app.agent import build_system_prompt
    from app.knowledge import core as core_mod

    core_mod.seed_if_missing()
    sid = _make_session("main")

    prompt = build_system_prompt(sid)

    assert "brand-new assistant in your first conversation" in prompt
    assert "mark_onboarded" in prompt
    assert "Your name is Atlas" not in prompt
    assert "## App context" in prompt
    assert prompt.index("What this is") < prompt.index("## App context")
    # Onboarding mode strips the shell-tools doc and tasks doc.
    assert "raw shell and filesystem tools" not in prompt
    assert "## How tasks work" not in prompt


def test_main_session_uses_general_prompt_when_flag_set(seeded_user, core_root):
    from app.agent import build_system_prompt
    from app.agent.tools.onboarding import do_set_assistant_name, do_set_user_name

    do_set_assistant_name("Atlas")
    do_set_user_name("Phil")
    _set_onboarded(seeded_user, datetime.now(UTC))
    sid = _make_session("main")

    prompt = build_system_prompt(sid)

    assert "## Identity" in prompt
    assert "Your name is Atlas." in prompt
    assert "You are talking with Phil." in prompt
    assert "brand-new assistant" not in prompt
    assert "## How tasks work" in prompt


def test_no_session_id_uses_onboarding_when_flag_null(seeded_user, core_root):
    """`session_id=None` defaults to main kind — should also onboard."""
    from app.agent import build_system_prompt
    from app.knowledge import core as core_mod

    core_mod.seed_if_missing()
    prompt = build_system_prompt(None)

    assert "brand-new assistant" in prompt
