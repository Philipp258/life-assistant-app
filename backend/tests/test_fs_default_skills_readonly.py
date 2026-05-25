"""Filesystem tools refuse writes/edits to backend/defaults/skills/."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fake_defaults_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point DEFAULTS_SKILLS_DIR at a tmp tree we can pre-populate."""
    target = tmp_path / "defaults_skills"
    target.mkdir(parents=True)
    import app.agent.tools.fs as fs_mod
    import app.config as config_mod

    monkeypatch.setattr(config_mod, "DEFAULTS_SKILLS_DIR", target, raising=True)
    monkeypatch.setattr(fs_mod, "DEFAULTS_SKILLS_DIR", target, raising=True)
    return target


def _seed_default(root: Path, name: str, body: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "SKILL.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_write_file_refuses_default_skill_path(fake_defaults_dir: Path):
    from app.agent.tools.fs import do_write_file

    target = fake_defaults_dir / "github" / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    # File doesn't exist yet — refusal must trigger before any write.
    result = do_write_file(str(target), "evil overwrite\n")
    assert "error" in result
    assert "read-only" in result["error"]
    assert not target.exists()


def test_write_file_refuses_relative_default_path(fake_defaults_dir: Path, monkeypatch):
    """Even when the agent uses a path that resolves under DEFAULTS_SKILLS_DIR."""
    from app.agent.tools.fs import do_write_file

    # Compute a path string that resolves to inside fake_defaults_dir.
    target = fake_defaults_dir / "self-update" / "SKILL.md"
    result = do_write_file(str(target), "x")
    assert "error" in result
    assert "read-only" in result["error"]


def test_edit_file_refuses_default_skill_path(fake_defaults_dir: Path):
    from app.agent.tools.fs import do_edit_file

    original = "---\nname: github\ndescription: D\n---\nbody\n"
    p = _seed_default(fake_defaults_dir, "github", original)
    result = do_edit_file(str(p), "body", "tampered")
    assert "error" in result
    assert "read-only" in result["error"]
    assert p.read_text(encoding="utf-8") == original


def test_write_file_allows_user_skill_path(tmp_path, monkeypatch):
    """Sanity: writing under data/skills still works."""
    import app.agent.tools.fs as fs_mod
    import app.config as config_mod

    user = tmp_path / "user_skills"
    user.mkdir()
    fake_defaults = tmp_path / "defaults_elsewhere"
    fake_defaults.mkdir()
    monkeypatch.setattr(config_mod, "DEFAULTS_SKILLS_DIR", fake_defaults, raising=True)
    monkeypatch.setattr(fs_mod, "DEFAULTS_SKILLS_DIR", fake_defaults, raising=True)

    from app.agent.tools.fs import do_write_file

    target = user / "myskill" / "SKILL.md"
    result = do_write_file(str(target), "---\nname: myskill\ndescription: mine\n---\nbody\n")
    assert result.get("ok") is True
    assert target.is_file()


def test_write_file_to_other_repo_path_still_works(tmp_path, monkeypatch):
    """Defaults guard must not block unrelated paths."""
    import app.agent.tools.fs as fs_mod
    import app.config as config_mod

    fake_defaults = tmp_path / "defaults"
    fake_defaults.mkdir()
    monkeypatch.setattr(config_mod, "DEFAULTS_SKILLS_DIR", fake_defaults, raising=True)
    monkeypatch.setattr(fs_mod, "DEFAULTS_SKILLS_DIR", fake_defaults, raising=True)

    from app.agent.tools.fs import do_write_file

    elsewhere = tmp_path / "scratch.md"
    result = do_write_file(str(elsewhere), "hello")
    assert result.get("ok") is True
    assert elsewhere.read_text(encoding="utf-8") == "hello"
