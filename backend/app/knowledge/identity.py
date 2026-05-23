"""Structured identity: the assistant's name and the user's name.

Both live in ``app_settings`` (whitelist-gated). The system prompt
injects them via a dedicated ``IDENTITY_PROMPT`` section; freeform
markdown in ``data/core/`` no longer carries names.

Onboarding populates both via the ``set_assistant_name`` /
``set_user_name`` agent tools, and ``mark_onboarded`` refuses to stamp
the user as done until both rows exist. Post-onboarding, resolvers
raise ``IdentityNotSet`` if either name is missing — there is no
fallback string.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.settings import service as settings_service

ASSISTANT_NAME_KEY = "assistant_name"
USER_NAME_KEY = "user_name"


class IdentityNotSet(RuntimeError):
    """Raised when a required identity name is missing from app_settings."""


def _get(db: Session, key: str) -> str | None:
    value = settings_service.get_runtime_setting(db, key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


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
    return settings_service.set_runtime_setting(db, key=ASSISTANT_NAME_KEY, value=name)


def set_user_name(db: Session, name: str) -> str:
    return settings_service.set_runtime_setting(db, key=USER_NAME_KEY, value=name)


def identity_complete(db: Session) -> bool:
    return get_assistant_name(db) is not None and get_user_name(db) is not None
