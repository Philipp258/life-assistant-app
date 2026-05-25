"""Identity is structured: stored in app_settings, no markdown parsing."""

from __future__ import annotations

import pytest


def test_set_and_resolve_assistant_name(_test_db):
    from app.db import SessionLocal
    from app.knowledge import identity

    with SessionLocal() as db:
        identity.set_assistant_name(db, "Atlas")

    assert identity.resolve_assistant_name() == "Atlas"


def test_set_and_resolve_user_name(_test_db):
    from app.db import SessionLocal
    from app.knowledge import identity

    with SessionLocal() as db:
        identity.set_user_name(db, "Phil")

    assert identity.resolve_user_name() == "Phil"


def test_resolver_raises_when_assistant_name_missing(_test_db):
    from app.db import SessionLocal
    from app.knowledge import identity
    from app.settings.models import AppSetting

    with SessionLocal() as db:
        db.query(AppSetting).filter(AppSetting.key == "assistant_name").delete()
        db.commit()

    with pytest.raises(identity.IdentityNotSet):
        identity.resolve_assistant_name()


def test_resolver_raises_when_user_name_missing(_test_db):
    from app.db import SessionLocal
    from app.knowledge import identity
    from app.settings.models import AppSetting

    with SessionLocal() as db:
        db.query(AppSetting).filter(AppSetting.key == "user_name").delete()
        db.commit()

    with pytest.raises(identity.IdentityNotSet):
        identity.resolve_user_name()


def test_identity_complete_requires_both(_test_db):
    from app.db import SessionLocal
    from app.knowledge import identity
    from app.settings.models import AppSetting

    with SessionLocal() as db:
        assert identity.identity_complete(db)
        db.query(AppSetting).filter(AppSetting.key == "user_name").delete()
        db.commit()
        assert not identity.identity_complete(db)


@pytest.mark.parametrize("bad", ["", "   ", "x" * 65])
def test_set_assistant_name_rejects_invalid(_test_db, bad: str):
    from app.db import SessionLocal
    from app.knowledge import identity

    with SessionLocal() as db:
        with pytest.raises(ValueError):
            identity.set_assistant_name(db, bad)


@pytest.mark.parametrize("bad", ["", "   ", "x" * 65])
def test_set_user_name_rejects_invalid(_test_db, bad: str):
    from app.db import SessionLocal
    from app.knowledge import identity

    with SessionLocal() as db:
        with pytest.raises(ValueError):
            identity.set_user_name(db, bad)


def test_set_strips_whitespace(_test_db):
    from app.db import SessionLocal
    from app.knowledge import identity

    with SessionLocal() as db:
        stored = identity.set_assistant_name(db, "  Atlas  ")
    assert stored == "Atlas"
    assert identity.resolve_assistant_name() == "Atlas"


def test_identity_section_in_general_prompt(_test_db):
    from app.agent import build_system_prompt

    prompt = build_system_prompt(None)

    assert "## Identity" in prompt
    assert "Your name is Atlas." in prompt
    assert "You are talking with Phil." in prompt


def test_build_system_prompt_raises_when_user_name_missing(_test_db):
    from app.agent import build_system_prompt
    from app.db import SessionLocal
    from app.knowledge.identity import IdentityNotSet
    from app.settings.models import AppSetting

    with SessionLocal() as db:
        db.query(AppSetting).filter(AppSetting.key == "user_name").delete()
        db.commit()

    with pytest.raises(IdentityNotSet):
        build_system_prompt(None)
