"""Structured identity: the assistant's name and the user's name.

Both live in ``app_settings`` (their own dedicated keys; not exposed via
the generic runtime-settings surface). The system prompt injects them
through a dedicated ``IDENTITY_PROMPT`` section; freeform markdown in
``data/core/`` no longer carries names.

Onboarding populates both via the ``set_assistant_name`` /
``set_user_name`` agent tools, and ``mark_onboarded`` refuses to stamp
the user as done until both rows exist. Post-onboarding, resolvers
raise ``IdentityNotSet`` if either name is missing — there is no
fallback string.
"""

from __future__ import annotations

from app.db import SessionLocal
from sqlalchemy.orm import Session

from app.settings.models import AppSetting

ASSISTANT_NAME_KEY = "assistant_name"
USER_NAME_KEY = "user_name"
MAX_NAME_LEN = 64


class IdentityNotSet(RuntimeError):
    """Raised when a required identity name is missing from app_settings."""


def _validate(name: str, *, field: str) -> str:
    stripped = name.strip()
    if not stripped:
        raise ValueError(f"{field} must be non-empty.")
    if len(stripped) > MAX_NAME_LEN:
        raise ValueError(f"{field} must be at most {MAX_NAME_LEN} characters.")
    return stripped


def _get(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    if row is None:
        return None
    stripped = row.value.strip()
    return stripped or None


def _set(db: Session, key: str, value: str) -> str:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    db.refresh(row)
    return row.value


def get_assistant_name(db: Session) -> str | None:
    return _get(db, ASSISTANT_NAME_KEY)


def get_user_name(db: Session) -> str | None:
    return _get(db, USER_NAME_KEY)


def resolve_assistant_name() -> str:
    with SessionLocal() as db:
        name = get_assistant_name(db)
    if name is None:
        raise IdentityNotSet("assistant_name is not set")
    return name


def resolve_user_name() -> str:
    with SessionLocal() as db:
        name = get_user_name(db)
    if name is None:
        raise IdentityNotSet("user_name is not set")
    return name


def set_assistant_name(db: Session, name: str) -> str:
    return _set(db, ASSISTANT_NAME_KEY, _validate(name, field="assistant_name"))


def set_user_name(db: Session, name: str) -> str:
    return _set(db, USER_NAME_KEY, _validate(name, field="user_name"))


def identity_complete(db: Session) -> bool:
    return get_assistant_name(db) is not None and get_user_name(db) is not None
