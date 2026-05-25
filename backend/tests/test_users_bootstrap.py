"""Singleton user row seeding."""

from __future__ import annotations

import pytest
import bcrypt
from sqlalchemy import delete, select

from app.users.models import User
from app.users.service import ensure_user


@pytest.fixture(autouse=True)
def _clear_users(db_session):
    """The conftest pre-seeds an onboarded user; bootstrap tests need a
    truly empty users table to exercise first-run behavior."""
    db_session.execute(delete(User))
    db_session.commit()


def test_ensure_user_creates_singleton(db_session):
    user = ensure_user(db_session)

    assert user.id == 1
    assert user.onboarded_at is None
    assert user.password_hash  # bcrypt string, not empty
    # First-boot hash is unguessable random — empty password must not match.
    assert not bcrypt.checkpw(b"", user.password_hash.encode())

    rows = db_session.execute(select(User)).scalars().all()
    assert len(rows) == 1


def test_ensure_user_idempotent(db_session):
    first = ensure_user(db_session)
    second = ensure_user(db_session)

    assert first.id == second.id
    assert first.password_hash == second.password_hash
    rows = db_session.execute(select(User)).scalars().all()
    assert len(rows) == 1
