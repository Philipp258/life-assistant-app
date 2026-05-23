"""`python -m app.knowledge.set_name` operator command."""

from __future__ import annotations

import pytest


def test_sets_assistant_name(_test_db, capsys) -> None:
    from app.knowledge import set_name

    rc = set_name.main(["--assistant", "Atlas"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "assistant_name set to 'Atlas'" in captured.out

    from app.db import SessionLocal
    from app.knowledge import identity

    with SessionLocal() as db:
        assert identity.get_assistant_name(db) == "Atlas"


def test_sets_user_name(_test_db, capsys) -> None:
    from app.knowledge import set_name

    rc = set_name.main(["--user", "Phil"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "user_name set to 'Phil'" in captured.out

    from app.db import SessionLocal
    from app.knowledge import identity

    with SessionLocal() as db:
        assert identity.get_user_name(db) == "Phil"


def test_sets_both(_test_db) -> None:
    from app.db import SessionLocal
    from app.knowledge import identity, set_name

    set_name.main(["--assistant", "Atlas", "--user", "Phil"])

    with SessionLocal() as db:
        assert identity.get_assistant_name(db) == "Atlas"
        assert identity.get_user_name(db) == "Phil"


def test_requires_at_least_one_flag(_test_db) -> None:
    from app.knowledge import set_name

    with pytest.raises(SystemExit):
        set_name.main([])


def test_rejects_empty_value(_test_db) -> None:
    from app.knowledge import set_name

    with pytest.raises(ValueError):
        set_name.main(["--assistant", "   "])
