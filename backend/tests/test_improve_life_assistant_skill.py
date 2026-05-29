"""Guard invariants of the default `improve-life-assistant` skill.

The skill is the per-task action prompt for spawned improvement items.
A drift here changes how every improvement task behaves, so the shape —
classify-first into the named class set, app classes acknowledged, closing
path that doesn't surface, conversational review, approval before write —
is asserted in code.
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
    assert "complete_task" in skill_text
    assert "No proposal" in skill_text


def test_app_classes_do_not_patch_repo_code(skill_text: str) -> None:
    collapsed = " ".join(skill_text.split())
    assert "do not edit repo files" in skill_text
    assert "use shell commands" in skill_text
    assert "coding and deploy changes can happen outside the app" in collapsed


def test_default_skill_reroutes_to_app_prompt(skill_text: str) -> None:
    assert "backend/defaults/skills/" in skill_text
    assert "read-only" in skill_text
    assert "app-prompt" in skill_text


def test_approval_before_durable_change_is_stated_plainly(skill_text: str) -> None:
    lowered = skill_text.lower()
    collapsed = " ".join(lowered.split())
    assert "propose first; write only after approval" in lowered
    assert "ask for approval before applying it" in collapsed


def test_user_facing_review_is_conversational(skill_text: str) -> None:
    lowered = skill_text.lower()
    assert "## User-facing review" in skill_text
    assert "normal conversation" in lowered
    assert "conversational, easy language" in lowered
    assert "it is fine to name app concepts" not in lowered


def test_review_move_allows_judgment_instead_of_forced_proposals(skill_text: str) -> None:
    lowered = skill_text.lower()
    collapsed = " ".join(lowered.split())
    assert "the goal is not to produce a memory edit" in collapsed
    assert "choose the next move with judgment" in lowered
    assert "no durable change follows" in lowered
    assert "one focused question" in lowered
    assert "approve, revise, or skip" in lowered


def test_abstraction_ladder_guards_against_overfitting(skill_text: str) -> None:
    lowered = skill_text.lower()
    collapsed = " ".join(lowered.split())
    assert "use the abstraction ladder" in lowered
    assert "raw case -> narrow rule -> broader principle -> intent / role" in lowered
    assert "think across the ladder" in lowered
    assert "without overfitting one moment" in collapsed
    assert "a narrow rule can be right" in collapsed
    assert "a broader principle is better" in collapsed
    assert "a role-level shift" in collapsed


def test_skill_avoids_canned_learning_examples(skill_text: str) -> None:
    lowered = skill_text.lower()
    assert "examples:" not in lowered
    assert "missed recommendation" not in lowered
    assert "recipe feedback" not in lowered
    assert "tone/style preference" not in lowered


def test_approval_before_persistence(skill_text: str) -> None:
    """The skill must preserve approval before persistent writes without
    spelling out every persistence tool."""
    lowered = skill_text.lower()
    assert "ask_user_choice" in skill_text
    assert "approval before applying" in lowered
    for tool_name in ("save_core_memory", "save_knowledge", "write_file", "edit_file"):
        assert tool_name not in skill_text


def test_approval_reply_is_handled_before_reasking(skill_text: str) -> None:
    lowered = skill_text.lower()
    assert "latest user message answers a previous `ask_user_choice`" in skill_text
    assert "never ask the same approval question twice" in lowered
    assert "make the approved change" in lowered
    assert "complete_task" in skill_text


def test_no_sibling_tasks(skill_text: str) -> None:
    assert "Don't spawn sibling tasks" in skill_text
