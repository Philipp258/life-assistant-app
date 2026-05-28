"""CLI: set_password updates the singleton hash."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.users.models import User
from app.users.service import verify_password


def test_set_password_updates_hash(db_session):
    # Conftest seeded a user with hash for "test-pass". Run the CLI's main()
    # via direct call (it opens its own SessionLocal, which conftest has
    # rebound to the test session factory).
    from app.users import set_password as cli

    cli.main("brand-new")

    db_session.expire_all()
    user = db_session.execute(select(User).limit(1)).scalar_one()
    assert verify_password("brand-new", user.password_hash)
    assert not verify_password("test-pass", user.password_hash)


def test_set_password_creates_user_when_missing(db_session):
    db_session.execute(delete(User))
    db_session.commit()

    from app.users import set_password as cli

    cli.main("first-pw")

    db_session.expire_all()
    user = db_session.execute(select(User).limit(1)).scalar_one()
    assert verify_password("first-pw", user.password_hash)


def test_set_password_rejects_empty():
    from app.users import set_password as cli

    with pytest.raises(SystemExit):
        cli.main("")


def test_needs_initial_password_exits_one_when_user_exists(db_session):
    from app.users import needs_initial_password as cli

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1


def test_needs_initial_password_exits_zero_when_user_missing(db_session):
    db_session.execute(delete(User))
    db_session.commit()

    from app.users import needs_initial_password as cli

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
