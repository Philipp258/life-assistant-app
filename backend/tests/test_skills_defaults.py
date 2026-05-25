"""Two-source skill listing: backend/defaults/skills/ + data/skills/."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest


@pytest.fixture
def two_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated DEFAULTS_SKILLS_DIR + SKILLS_DIR per test."""
    defaults = tmp_path / "defaults"
    user = tmp_path / "user"
    defaults.mkdir(parents=True)
    user.mkdir(parents=True)
    import app.config as config_mod
    import app.skills.store as store_mod

    monkeypatch.setattr(config_mod, "DEFAULTS_SKILLS_DIR", defaults, raising=True)
    monkeypatch.setattr(config_mod, "SKILLS_DIR", user, raising=True)
    monkeypatch.setattr(store_mod, "DEFAULTS_SKILLS_DIR", defaults, raising=True)
    monkeypatch.setattr(store_mod, "SKILLS_DIR", user, raising=True)
    return defaults, user


def _write(root: Path, name: str, description: str) -> None:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nbody\n",
        encoding="utf-8",
    )


def test_lists_defaults_only(two_dirs):
    defaults, _user = two_dirs
    _write(defaults, "github", "GitHub stuff")

    from app.skills import store

    metas = store.list_skills()
    assert len(metas) == 1
    assert metas[0].name == "github"
    assert metas[0].source == "default"


def test_merges_defaults_and_user(two_dirs):
    defaults, user = two_dirs
    _write(defaults, "github", "GitHub")
    _write(defaults, "self-update", "Deploy")
    _write(user, "notion", "Notes")
    _write(user, "weather", "Forecast")

    from app.skills import store

    metas = store.list_skills()
    assert [m.name for m in metas] == ["github", "notion", "self-update", "weather"]
    by_name = {m.name: m for m in metas}
    assert by_name["github"].source == "default"
    assert by_name["self-update"].source == "default"
    assert by_name["notion"].source == "user"
    assert by_name["weather"].source == "user"


def test_user_collision_with_default_skipped(two_dirs, caplog):
    defaults, user = two_dirs
    _write(defaults, "github", "official GitHub")
    _write(user, "github", "user override")

    from app.skills import store

    with caplog.at_level(logging.WARNING, logger="app.skills.store"):
        metas = store.list_skills()

    assert len(metas) == 1
    assert metas[0].source == "default"
    assert metas[0].description == "official GitHub"
    assert any("shadows a default" in rec.message for rec in caplog.records)


def test_defaults_dir_missing_returns_user_only(tmp_path, monkeypatch):
    """If DEFAULTS_SKILLS_DIR doesn't exist, list_skills still works."""
    user = tmp_path / "user"
    user.mkdir()
    missing = tmp_path / "nope"  # never created
    import app.config as config_mod
    import app.skills.store as store_mod

    monkeypatch.setattr(config_mod, "DEFAULTS_SKILLS_DIR", missing, raising=True)
    monkeypatch.setattr(config_mod, "SKILLS_DIR", user, raising=True)
    monkeypatch.setattr(store_mod, "DEFAULTS_SKILLS_DIR", missing, raising=True)
    monkeypatch.setattr(store_mod, "SKILLS_DIR", user, raising=True)
    _write(user, "myskill", "mine")

    from app.skills import store

    metas = store.list_skills()
    assert [m.name for m in metas] == ["myskill"]
    assert metas[0].source == "user"


def test_read_skill_prefers_default_on_collision(two_dirs):
    defaults, user = two_dirs
    _write(defaults, "github", "official")
    _write(user, "github", "shadow")

    from app.skills import store

    skill = store.read_skill("github")
    assert skill.source == "default"
    assert skill.description == "official"


def test_read_skill_returns_user_when_no_default(two_dirs):
    _defaults, user = two_dirs
    _write(user, "notion", "user notion")

    from app.skills import store

    skill = store.read_skill("notion")
    assert skill.source == "user"
    assert skill.description == "user notion"


def test_real_shipped_defaults_listed():
    """Sanity: the three real default SKILL.md files in
    backend/defaults/skills/ exist and are picked up by list_skills.

    This protects against accidentally deleting a tracked default.
    Uses the real DEFAULTS_SKILLS_DIR (the autouse fixture in conftest
    only swaps SKILLS_DIR, CORE_DIR, KNOWLEDGE_DIR — DEFAULTS stays
    pointed at backend/defaults/skills/).
    """
    from app.skills import store

    metas = store.list_skills()
    names = {m.name: m for m in metas}
    for required in ("add-skills", "improve-life-assistant", "self-update"):
        assert required in names, f"default skill {required!r} missing from list"
        assert names[required].source == "default"
