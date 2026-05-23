"""Guard invariants of the default `improve-life-assistant` skill.

The skill is the per-task action prompt for spawned improvement items.
A drift here changes how every improvement task behaves, so the shape —
classify-first into the named class set, app classes acknowledged, closing
path that doesn't surface, approval before write — is asserted in code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SKILL_PATH = (
    Path(__file__).resolve().parents[1]
    / "defaults"
    / "skills"
    / "improve-life-assistant"
    / "SKILL.md"
)


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_file_exists() -> None:
    assert SKILL_PATH.is_file()


def test_frontmatter_present(skill_text: str) -> None:
    assert skill_text.startswith("---\n")
    head, _, _ = skill_text[4:].partition("\n---\n")
    assert "name: improve-life-assistant" in head
    assert "description:" in head


def test_classify_first_step(skill_text: str) -> None:
    assert "## Classify first" in skill_text


def test_all_classes_named(skill_text: str) -> None:
    """App classes are intentional — without them the agent never considers
    that the app or a baked-in prompt could be at fault and forces every
    moment into a memory/skill/knowledge change."""
    for cls in (
        "**behavior**",
        "**user-fact**",
        "**skill**",
        "**knowledge**",
        "**app-bug**",
        "**app-prompt**",
        "**skip**",
    ):
        assert cls in skill_text, f"missing class label {cls}"


def test_app_classes_close_without_surfacing(skill_text: str) -> None:
    assert "app-bug" in skill_text
    assert "app-prompt" in skill_text
    assert "close the task" in skill_text
    assert "No proposal" in skill_text


def test_default_skill_reroutes_to_app_prompt(skill_text: str) -> None:
    assert "backend/defaults/skills/" in skill_text
    assert "read-only" in skill_text
    assert "app-prompt" in skill_text


def test_concrete_change_before_apply(skill_text: str) -> None:
    """The skill should ask for a concrete change (diff / exact wording),
    not a paraphrase, before user approval."""
    lowered = skill_text.lower()
    assert "diff" in lowered
    assert "not a paraphrase" in lowered or "exact" in lowered


def test_approval_before_persistence(skill_text: str) -> None:
    """Some form of asking-before-applying must be present — exact phrasing
    is the agent's call."""
    lowered = skill_text.lower()
    assert "go-ahead" in lowered or "approval" in lowered or "ask" in lowered
    assert "apply" in lowered


def test_no_sibling_tasks(skill_text: str) -> None:
    assert "Don't spawn sibling tasks" in skill_text
