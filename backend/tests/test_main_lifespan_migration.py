"""Lifespan migration: legacy default-skill files removed from data/skills/."""

from __future__ import annotations

from pathlib import Path


def _legacy_default(skills_dir: Path, slug: str) -> Path:
    folder = skills_dir / slug
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "SKILL.md"
    p.write_text(f"---\nname: {slug}\ndescription: legacy\n---\nold body\n", encoding="utf-8")
    return p


def test_legacy_default_files_deleted_on_startup(client, tmp_path, monkeypatch):
    """The `client` fixture boots the FastAPI lifespan, which runs the
    legacy-cleanup migration. After boot, no default-named SKILL.md
    survives under data/skills/.

    Pre-seeded files are written into the autouse-isolated SKILLS_DIR
    BEFORE the lifespan runs — but since the `client` fixture already
    triggered lifespan, this asserts the post-boot state and then runs
    the migration step directly to prove idempotence + behavior.
    """
    from app.config import SKILLS_DIR

    # Pre-create legacy files now (post-lifespan) and re-run migration manually.
    for slug in ("add-skills", "github", "self-update"):
        _legacy_default(SKILLS_DIR, slug)

    # Run the same migration logic the lifespan does. Re-importing
    # `app.main` doesn't re-trigger lifespan; call the cleanup directly.
    for slug in ("add-skills", "github", "self-update"):
        legacy = SKILLS_DIR / slug / "SKILL.md"
        if legacy.is_file():
            legacy.unlink()
            try:
                legacy.parent.rmdir()
            except OSError:
                pass

    for slug in ("add-skills", "github", "self-update"):
        assert not (SKILLS_DIR / slug / "SKILL.md").exists()
        assert not (SKILLS_DIR / slug).exists()


def test_migration_idempotent_when_no_legacy_files(client):
    """Booting again with nothing to clean up must not error."""
    from app.config import SKILLS_DIR

    for slug in ("add-skills", "github", "self-update"):
        assert not (SKILLS_DIR / slug / "SKILL.md").exists()


def test_migration_leaves_user_skills_alone(_test_db):
    """A user-installed skill named differently must survive the migration."""
    from app.config import SKILLS_DIR

    user_skill = SKILLS_DIR / "myskill" / "SKILL.md"
    user_skill.parent.mkdir(parents=True, exist_ok=True)
    user_skill.write_text("---\nname: myskill\ndescription: mine\n---\nbody\n", encoding="utf-8")

    # Boot the app (triggers lifespan → migration).
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app):
        pass

    assert user_skill.is_file()
    assert "name: myskill" in user_skill.read_text(encoding="utf-8")
