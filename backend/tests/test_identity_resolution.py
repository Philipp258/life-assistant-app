"""Phase 2: assistant name parsed from behavior.md + injected into prompts."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def core_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "core"
    root.mkdir()
    import app.config as config_mod
    from app.knowledge import core as core_mod

    monkeypatch.setattr(config_mod, "CORE_DIR", root, raising=True)
    monkeypatch.setattr(core_mod, "CORE_DIR", root, raising=True)
    return root


def _write_behavior(core_root: Path, body: str) -> None:
    (core_root / "behavior.md").write_text(body, encoding="utf-8")


def test_resolves_name_from_first_line(core_root: Path):
    from app.knowledge.identity import resolve_assistant_name

    _write_behavior(core_root, "**Name:** Atlas\n\nBe terse.\n")
    assert resolve_assistant_name() == "Atlas"


def test_resolves_name_after_blank_lines(core_root: Path):
    from app.knowledge.identity import resolve_assistant_name

    _write_behavior(core_root, "\n\n**Name:** Atlas\n\nBe terse.\n")
    assert resolve_assistant_name() == "Atlas"


def test_falls_back_when_default_seed_in_place(core_root: Path):
    from app.knowledge import core as core_mod
    from app.knowledge.identity import FALLBACK_NAME, resolve_assistant_name

    core_mod.seed_if_missing()
    assert resolve_assistant_name() == FALLBACK_NAME


def test_falls_back_when_file_missing(core_root: Path):
    from app.knowledge.identity import FALLBACK_NAME, resolve_assistant_name

    assert resolve_assistant_name() == FALLBACK_NAME


def test_only_scans_first_8_lines(core_root: Path):
    from app.knowledge.identity import FALLBACK_NAME, resolve_assistant_name

    body = "\n".join(["filler"] * 20 + ["**Name:** Atlas"])
    _write_behavior(core_root, body)
    assert resolve_assistant_name() == FALLBACK_NAME


def test_handles_extra_whitespace(core_root: Path):
    from app.knowledge.identity import resolve_assistant_name

    _write_behavior(core_root, "  **Name:**   Atlas   \n")
    assert resolve_assistant_name() == "Atlas"


def test_multi_word_name(core_root: Path):
    from app.knowledge.identity import resolve_assistant_name

    _write_behavior(core_root, "**Name:** Captain Nemo\n")
    assert resolve_assistant_name() == "Captain Nemo"


def test_name_interpolated_into_general_prompt(_test_db, core_root: Path):
    """Conftest seeds the singleton user as already-onboarded so the
    general-prompt branch runs."""
    from app.agent import build_system_prompt

    _write_behavior(core_root, "**Name:** Atlas\n")
    prompt = build_system_prompt(None)

    assert "You are Atlas, the assistant inside Life Assistant" in prompt


def test_fallback_name_interpolated_when_unbranded(_test_db, core_root: Path):
    from app.agent import build_system_prompt
    from app.knowledge import core as core_mod

    core_mod.seed_if_missing()
    prompt = build_system_prompt(None)

    assert "You are Assistant, the assistant inside Life Assistant" in prompt
