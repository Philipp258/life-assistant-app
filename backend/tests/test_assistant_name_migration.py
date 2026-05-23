"""One-shot Alembic data migration: behavior.md `**Name:** X` → app_settings."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "9c1de4f7b201_assistant_name_to_app_settings.py"
)


@pytest.fixture
def migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "assistant_name_migration_under_test", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def core_root(tmp_path: Path) -> Path:
    root = tmp_path / "core"
    root.mkdir()
    return root


def _wipe_seed(db_session) -> None:
    from app.settings.models import AppSetting

    db_session.query(AppSetting).filter(AppSetting.key == "assistant_name").delete()
    db_session.commit()


def test_imports_name_and_strips_line(
    _test_db, db_session, core_root: Path, migration_module: ModuleType
) -> None:
    from app.settings.models import AppSetting

    _wipe_seed(db_session)
    (core_root / "behavior.md").write_text(
        "**Name:** Atlas\n\nBe terse.\n", encoding="utf-8"
    )

    with db_session.bind.begin() as conn:
        migration_module.apply_to(conn, core_root / "behavior.md")

    db_session.expire_all()
    row = db_session.get(AppSetting, "assistant_name")
    assert row is not None
    assert row.value == "Atlas"
    assert (core_root / "behavior.md").read_text(encoding="utf-8") == "Be terse.\n"


def test_no_op_when_no_name_line(
    _test_db, db_session, core_root: Path, migration_module: ModuleType
) -> None:
    from app.settings.models import AppSetting

    _wipe_seed(db_session)
    body = "# How the assistant should behave\n\nBe terse.\n"
    (core_root / "behavior.md").write_text(body, encoding="utf-8")

    with db_session.bind.begin() as conn:
        migration_module.apply_to(conn, core_root / "behavior.md")

    db_session.expire_all()
    assert db_session.get(AppSetting, "assistant_name") is None
    assert (core_root / "behavior.md").read_text(encoding="utf-8") == body


def test_no_op_when_behavior_md_missing(
    _test_db, db_session, core_root: Path, migration_module: ModuleType
) -> None:
    from app.settings.models import AppSetting

    _wipe_seed(db_session)
    with db_session.bind.begin() as conn:
        migration_module.apply_to(conn, core_root / "behavior.md")

    db_session.expire_all()
    assert db_session.get(AppSetting, "assistant_name") is None


def test_rerun_is_idempotent(
    _test_db, db_session, core_root: Path, migration_module: ModuleType
) -> None:
    from app.settings.models import AppSetting

    _wipe_seed(db_session)
    path = core_root / "behavior.md"
    path.write_text("**Name:** Atlas\n\nBe terse.\n", encoding="utf-8")

    with db_session.bind.begin() as conn:
        migration_module.apply_to(conn, path)

    # Simulate someone restoring the line (or a stale file) — INSERT OR
    # IGNORE keeps the original value.
    path.write_text("**Name:** Different\n\nBe terse.\n", encoding="utf-8")
    with db_session.bind.begin() as conn:
        migration_module.apply_to(conn, path)

    db_session.expire_all()
    row = db_session.get(AppSetting, "assistant_name")
    assert row is not None
    assert row.value == "Atlas"


def test_strips_only_top_of_file(
    _test_db, db_session, core_root: Path, migration_module: ModuleType
) -> None:
    """A `**Name:** …` mention deeper in the body must be left alone."""
    from app.settings.models import AppSetting

    _wipe_seed(db_session)
    body = (
        "**Name:** Atlas\n"
        "\n"
        "Be terse.\n"
        "\n"
        "Earlier draft said **Name:** something else.\n"
    )
    (core_root / "behavior.md").write_text(body, encoding="utf-8")

    with db_session.bind.begin() as conn:
        migration_module.apply_to(conn, core_root / "behavior.md")

    db_session.expire_all()
    row = db_session.get(AppSetting, "assistant_name")
    assert row is not None
    assert row.value == "Atlas"
    after = (core_root / "behavior.md").read_text(encoding="utf-8")
    assert after.startswith("Be terse.\n")
    assert "Earlier draft said **Name:** something else." in after
