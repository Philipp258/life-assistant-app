"""Phase 4: GET /api/chat/main injects an assistant greeting on fresh installs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.chat.service import ONBOARDING_GREETING


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
def onboarding_user(_test_db):
    """Singleton user, onboarded_at = NULL (mid-onboarding).

    The conftest fixture seeds an already-onboarded row by default; this
    fixture nulls that timestamp so tests can exercise the pre-onboarding
    branch.
    """
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.users.models import User

    with SessionLocal() as db:
        user = db.scalars(select(User)).first()
        user.onboarded_at = None
        db.commit()
        return user.id


def _mark_done(user_id: int) -> None:
    from app.db import SessionLocal
    from app.users.models import User

    with SessionLocal() as db:
        db.get(User, user_id).onboarded_at = datetime.now(UTC)
        db.commit()


def _main_session_message_count() -> int:
    from sqlalchemy import select
    from app.chat.models import ChatSession, Message
    from app.db import SessionLocal

    with SessionLocal() as db:
        main = db.scalars(select(ChatSession).where(ChatSession.kind == "main")).first()
        if main is None:
            return 0
        return (
            db.scalar(select(Message).where(Message.session_id == main.id).order_by(Message.id))
            and len(db.scalars(select(Message).where(Message.session_id == main.id)).all())
            or 0
        )


def test_greeting_inserted_when_onboarding_and_empty(client, onboarding_user, core_root):
    response = client.get("/api/chat/main")

    assert response.status_code == 200
    body = response.json()
    assert body["is_onboarding"] is True
    assert len(body["messages"]) == 1
    msg = body["messages"][0]
    assert msg["role"] == "assistant"
    assert ONBOARDING_GREETING in str(msg)


def test_greeting_persisted_in_db(client, onboarding_user, core_root):
    client.get("/api/chat/main")

    assert _main_session_message_count() == 1


def test_greeting_idempotent_on_repeat_calls(client, onboarding_user, core_root):
    client.get("/api/chat/main")
    client.get("/api/chat/main")
    client.get("/api/chat/main")

    assert _main_session_message_count() == 1


def test_no_greeting_when_history_present(client, onboarding_user, core_root):
    """If main session already has any message, do not auto-inject."""
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from app.chat.service import get_or_create_main_session, save_new_messages
    from app.db import SessionLocal

    with SessionLocal() as db:
        main = get_or_create_main_session(db)
        save_new_messages(
            db,
            main.id,
            [ModelRequest(parts=[UserPromptPart(content="hi")])],
        )

    response = client.get("/api/chat/main")

    assert response.status_code == 200
    body = response.json()
    assert len(body["messages"]) == 1
    assert ONBOARDING_GREETING not in str(body["messages"][0])
    assert _main_session_message_count() == 1


def test_no_greeting_when_onboarded(client, onboarding_user, core_root):
    _mark_done(onboarding_user)

    response = client.get("/api/chat/main")

    body = response.json()
    assert body["is_onboarding"] is False
    assert body["messages"] == []
    assert _main_session_message_count() == 0
