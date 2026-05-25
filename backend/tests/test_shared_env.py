"""Secrets live in one machine-level file shared by every worktree; the
per-worktree .env only overrides it. Verifies the path resolution and
the pydantic-settings load order (later file wins, missing files skipped)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings, _shared_env_path

_LF_VARS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "SESSION_SECRET")


@pytest.fixture(autouse=True)
def _no_inherited_secrets(monkeypatch: pytest.MonkeyPatch):
    # OS env outranks dotenv in pydantic-settings; make sure a shell that
    # exported these doesn't mask what the test files declare.
    for var in _LF_VARS:
        monkeypatch.delenv(var, raising=False)


def test_shared_env_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LIFE_ASSISTANT_SHARED_ENV", raising=False)
    assert _shared_env_path() == Path.home() / ".config" / "life-assistant" / ".env"


def test_shared_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LIFE_ASSISTANT_SHARED_ENV", "/tmp/custom-life-assistant.env")
    assert _shared_env_path() == Path("/tmp/custom-life-assistant.env")


def test_worktree_env_overrides_shared(tmp_path: Path):
    shared = tmp_path / "shared.env"
    shared.write_text("LANGFUSE_PUBLIC_KEY=shared_pub\nLANGFUSE_SECRET_KEY=only_in_shared\n")
    local = tmp_path / "worktree.env"
    local.write_text("LANGFUSE_PUBLIC_KEY=worktree_pub\n")

    s = Settings(_env_file=(shared, local))

    # Worktree .env wins where both define it...
    assert s.langfuse_public_key == "worktree_pub"
    # ...but shared-only secrets still come through.
    assert s.langfuse_secret_key == "only_in_shared"


def test_missing_shared_file_is_skipped(tmp_path: Path):
    local = tmp_path / "worktree.env"
    local.write_text("LANGFUSE_PUBLIC_KEY=worktree_pub\n")

    s = Settings(_env_file=(tmp_path / "does-not-exist.env", local))

    assert s.langfuse_public_key == "worktree_pub"
