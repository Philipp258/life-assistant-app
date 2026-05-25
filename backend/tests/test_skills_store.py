"""Skill store: filesystem walk, frontmatter parsing, prompt rendering, seeding."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated SKILLS_DIR + empty DEFAULTS_SKILLS_DIR per test.

    These tests target the user-skill walk + frontmatter parsing in
    isolation, so we blank the defaults dir to keep `list_skills()`
    returning only what the test wrote.
    """
    target = tmp_path / "skills"
    target.mkdir(parents=True)
    empty_defaults = tmp_path / "defaults_empty"
    empty_defaults.mkdir(parents=True)
    import app.config as config_mod
    import app.skills.store as store_mod

    monkeypatch.setattr(config_mod, "SKILLS_DIR", target, raising=True)
    monkeypatch.setattr(store_mod, "SKILLS_DIR", target, raising=True)
    monkeypatch.setattr(config_mod, "DEFAULTS_SKILLS_DIR", empty_defaults, raising=True)
    monkeypatch.setattr(store_mod, "DEFAULTS_SKILLS_DIR", empty_defaults, raising=True)
    return target


def _write_skill(root: Path, name: str, body: str) -> None:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(body, encoding="utf-8")


def test_list_skills_empty(skills_dir: Path):
    from app.skills import store

    assert store.list_skills() == []


def test_list_skills_parses_frontmatter(skills_dir: Path):
    from app.skills import store

    _write_skill(
        skills_dir,
        "foo",
        "---\nname: foo\ndescription: Does foo things.\n---\n\nbody here\n",
    )
    metas = store.list_skills()
    assert len(metas) == 1
    assert metas[0].name == "foo"
    assert metas[0].description == "Does foo things."
    assert metas[0].path.endswith("data/skills/foo/SKILL.md") or metas[0].path.endswith(
        "foo/SKILL.md"
    )


def test_list_skills_skips_folders_without_skill_md(skills_dir: Path):
    from app.skills import store

    bare = skills_dir / "half-baked"
    bare.mkdir()
    (bare / "notes.md").write_text("just notes", encoding="utf-8")
    _write_skill(
        skills_dir,
        "real",
        "---\nname: real\ndescription: real one\n---\nbody\n",
    )
    metas = store.list_skills()
    assert [m.name for m in metas] == ["real"]


def test_list_skills_tolerates_malformed_frontmatter(skills_dir: Path):
    from app.skills import store

    # Folder name ok, but frontmatter is missing both fields entirely.
    _write_skill(
        skills_dir,
        "weird",
        "no frontmatter at all just body\n",
    )
    # Frontmatter present but missing 'name' falls back to folder name;
    # missing 'description' becomes empty string.
    _write_skill(
        skills_dir,
        "partial",
        "---\ndescription: only desc\n---\nbody\n",
    )
    metas = {m.name: m for m in store.list_skills()}
    assert metas["weird"].description == ""
    assert metas["partial"].description == "only desc"


def test_list_skills_sorted_by_name(skills_dir: Path):
    from app.skills import store

    for n in ("zeta", "alpha", "mu"):
        _write_skill(skills_dir, n, f"---\nname: {n}\ndescription: x\n---\nbody\n")
    metas = store.list_skills()
    assert [m.name for m in metas] == ["alpha", "mu", "zeta"]


def test_read_skill_returns_body(skills_dir: Path):
    from app.skills import store

    _write_skill(
        skills_dir,
        "foo",
        "---\nname: foo\ndescription: D\n---\n\n# Foo\n\nDo a thing.\n",
    )
    skill = store.read_skill("foo")
    assert skill.name == "foo"
    assert skill.description == "D"
    assert "Do a thing." in skill.body


def test_read_skill_path_traversal_rejected(skills_dir: Path):
    from app.skills import store

    for bad in ("../etc", "/abs", "foo/bar", "..", "Foo", "-bad", "bad-"):
        with pytest.raises(store.SkillError):
            store.read_skill(bad)


def test_read_skill_missing_raises(skills_dir: Path):
    from app.skills import store

    with pytest.raises(store.SkillError, match="not found"):
        store.read_skill("nonexistent")


def test_render_skills_for_prompt_compact_format(skills_dir: Path):
    from app.skills import store

    _write_skill(
        skills_dir,
        "foo",
        "---\nname: foo\ndescription: Does foo.\n---\nbody\n",
    )
    _write_skill(
        skills_dir,
        "bar",
        "---\nname: bar\ndescription: Does bar.\n---\nbody\n",
    )
    blob = store.render_skills_for_prompt(store.list_skills())
    assert blob.startswith("<skills>")
    assert blob.endswith("</skills>")
    assert "- bar: Does bar." in blob
    assert "- foo: Does foo." in blob
    # Sorted: bar should appear before foo in the rendered string.
    assert blob.index("- bar:") < blob.index("- foo:")


def test_render_skills_for_prompt_empty_list():
    from app.skills import store

    blob = store.render_skills_for_prompt([])
    assert blob == "<skills>(none installed)</skills>"


def test_render_skills_for_prompt_includes_path(skills_dir: Path):
    """Each rendered entry surfaces the skill's actual SKILL.md path so
    the agent can `read_file` it without guessing the root — the bug
    that closes #67 was the prompt hard-coding `data/skills/<name>/`
    even for default skills under `backend/defaults/skills/`."""
    from app.skills import store

    _write_skill(
        skills_dir,
        "foo",
        "---\nname: foo\ndescription: Does foo.\n---\nbody\n",
    )
    blob = store.render_skills_for_prompt(store.list_skills())
    assert "foo/SKILL.md" in blob
    assert "(read " in blob
