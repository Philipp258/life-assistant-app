"""User singleton bootstrap.

Life Assistant is single-user today. The `users` table holds one row, created at
first boot and reused thereafter. The password hash lives only on this
row; the login flow verifies against it. On a fresh boot with no row,
we seed an unguessable random hash so the app starts cleanly — the
operator must run `make set-password PASSWORD=...` (or
`python -m app.users.set_password ...`) before anyone can log in.
"""

from __future__ import annotations

import logging
import secrets

import bcrypt
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.datetime_utils import utc_now
from app.db import SessionLocal
from app.users.models import User

log = logging.getLogger(__name__)


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _get_singleton(db: Session) -> User | None:
    return db.execute(select(User).order_by(User.id).limit(1)).scalar_one_or_none()


def is_onboarding() -> bool:
    """True while the singleton user has no onboarded_at timestamp.

    Conservative on uncertainty: if the table is missing (e.g. a unit
    test that never created it) or no row exists, returns False so the
    main prompt renders normally instead of forcing the onboarding
    ritual on every caller. The lifespan bootstrap is responsible for
    seeding the row before real requests reach the agent.
    """
    try:
        with SessionLocal() as db:
            user = _get_singleton(db)
    except OperationalError:
        return False
    if user is None:
        return False
    return user.onboarded_at is None


def mark_onboarded(db: Session) -> bool:
    """Stamp onboarded_at = now() on the singleton user.

    Returns True if the call performed the write, False if it was a
    no-op (already onboarded).
    """
    user = _get_singleton(db)
    if user is None:
        raise RuntimeError("singleton user row missing — lifespan did not seed it")
    if user.onboarded_at is not None:
        return False
    user.onboarded_at = utc_now()
    db.commit()
    return True


def ensure_user(db: Session) -> User:
    """Return the singleton user row, creating it on first boot.

    First-boot row is seeded with an unguessable random hash. The app
    boots fine but no one can log in until `set_password` runs. This
    keeps first-run behaviour deterministic without leaking a password
    via env vars.
    """
    user = db.execute(select(User).order_by(User.id).limit(1)).scalar_one_or_none()
    if user is not None:
        return user

    user = User(password_hash=_hash_password(secrets.token_urlsafe(32)))
    db.add(user)
    db.commit()
    db.refresh(user)
    log.warning(
        "users.password_hash seeded with random unguessable value; "
        "run `make set-password PASSWORD=...` before logging in.",
    )
    return user


def set_password(db: Session, plain: str) -> User:
    """Set the singleton user's password hash. Creates the row if missing."""
    user = ensure_user(db)
    user.password_hash = _hash_password(plain)
    db.commit()
    db.refresh(user)
    return user
