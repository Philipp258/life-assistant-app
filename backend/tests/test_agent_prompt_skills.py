"""System-prompt assembly: skills footer + per-kind branching."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated SKILLS_DIR + empty DEFAULTS_SKILLS_DIR.

    Prompt-shape tests want to control exactly which skills appear in
    the rendered footer, so we blank the real defaults dir too.
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


def _write_skill(root: Path, name: str, description: str) -> None:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nbody\n",
        encoding="utf-8",
    )


def _build_prompt(session_id: int | None) -> str:
    from app.agent import build_system_prompt

    return build_system_prompt(session_id)


def test_system_prompt_main_lists_skills_as_routing_signal(_test_db, skills_dir: Path):
    """Main chat sees the skill catalog so it can route to a task, but the
    blurb frames skills as task work, not something to activate inline."""
    _write_skill(skills_dir, "foo", "Does foo.")

    from app.chat.service import get_or_create_main_session

    Session = _test_db
    with Session() as s:
        main = get_or_create_main_session(s)
        sid = main.id

    prompt = _build_prompt(sid)
    assert "## Skills" in prompt
    assert "<skills>" in prompt
    assert "- foo: Does foo." in prompt
    # Routing framing, not the task-chat activation hint.
    assert "create a task" in prompt
    assert "skills activate and run in the task chat, not here" in prompt
    assert "read that exact path with `read_file` to activate the skill" not in prompt


def test_system_prompt_task_includes_skills_block(_test_db, skills_dir: Path):
    _write_skill(skills_dir, "bar", "Does bar.")

    from app.tasks import service as tasks_service
    from app.tasks.schemas import TaskCreate

    Session = _test_db
    with Session() as s:
        task = tasks_service.create_task(s, TaskCreate(title="T1"))
        sid = task.chat_session_id

    prompt = _build_prompt(sid)
    assert "<skills>" in prompt
    assert "- bar: Does bar." in prompt


def test_system_prompt_task_no_skills_renders_empty_block(_test_db, skills_dir: Path):
    from app.tasks import service as tasks_service
    from app.tasks.schemas import TaskCreate

    Session = _test_db
    with Session() as s:
        task = tasks_service.create_task(s, TaskCreate(title="T1"))
        sid = task.chat_session_id

    prompt = _build_prompt(sid)
    assert "<skills>(none installed)</skills>" in prompt


def test_main_prompt_explains_task_coordination_from_main_chat(_test_db, skills_dir: Path):
    from app.chat.service import get_or_create_main_session

    Session = _test_db
    with Session() as s:
        main = get_or_create_main_session(s)
        sid = main.id

    prompt = _build_prompt(sid)
    # Narrow role: conversational interface, task relay, result communication.
    assert "one foreground conversation" in prompt
    assert "task chats do focused work" in prompt
    assert "relay work to tasks" in prompt
    assert "communicate task results, blockers, and questions" in prompt
    assert "do nothing else" in prompt
    assert "web-based work" not in prompt
    assert "mutating" not in prompt
    # Main chat keeps inspect tools to ground answers, but act/web work
    # is delegated — the inspect section is present, the work section is not.
    assert "## Inspecting files" in prompt
    assert "## Work tools" not in prompt
    assert "You also have raw shell and filesystem tools" not in prompt
    # Steering a running task: relay via relay_to_task, not a silent
    # description edit the running agent would miss.
    assert "relay_to_task" in prompt
    assert "do not edit a running task's description" not in prompt
    # Task chats own execution and report back through lifecycle handoffs;
    # main chat coordinates rather than supervising the work.
    assert "should not supervise task execution by watching task chats" in prompt
    assert "Task chats report back through lifecycle handoffs" in prompt


def test_main_prompt_routes_explicit_self_improvement_requests(_test_db, skills_dir: Path):
    from app.chat.service import get_or_create_main_session

    Session = _test_db
    with Session() as s:
        main = get_or_create_main_session(s)
        sid = main.id

    prompt = _build_prompt(sid)

    assert "Self-improvement only runs when" in prompt
    assert "asks to treat something as an improvement" in prompt
    assert "create an assistant task with `labels=['improve-life-assistant']`" in prompt
    assert "hand off with `ask_user_choice`" in prompt
    assert "learn from a correction" not in prompt
    assert "Other feedback stays in the current conversation" in prompt
    assert "routine improvement jobs review recent activity" in prompt


def test_shared_app_context_appears_before_main_chat_role(_test_db, skills_dir: Path):
    from app.chat.service import get_or_create_main_session

    Session = _test_db
    with Session() as s:
        main = get_or_create_main_session(s)
        sid = main.id

    prompt = _build_prompt(sid)
    assert "## App context" in prompt
    assert prompt.index("## App context") < prompt.index("## Main chat")
    assert "It has chats, tasks, knowledge notes, core memory, and skills" in prompt
    assert "Main chat is for conversation and coordination" in prompt
    assert "task chats hold focused work" in prompt
    assert "durable sources of truth" in prompt
    assert "chat scrollback is conversational context" in prompt
    assert "Where you are operating matters" not in prompt
    assert "implementation labels" not in prompt


def test_prompt_requires_public_routes_for_user_facing_app_links(_test_db, skills_dir: Path):
    from app.chat.service import get_or_create_main_session

    Session = _test_db
    with Session() as s:
        main = get_or_create_main_session(s)
        sid = main.id

    prompt = _build_prompt(sid)
    assert "## App links" in prompt
    assert "[<task title>](/tasks/<id>)" in prompt
    assert "[<note title>](/know/open/<path>)" in prompt
    assert "/know/open/Projects/Life%20Assistant%20MVP%20Roadmap.md" in prompt
    assert "Do not emit `knowledge://...` links." in prompt


def test_task_prompt_requires_visible_status_when_web_research_is_blocked(
    _test_db, skills_dir: Path
):
    from app.tasks import service as tasks_service
    from app.tasks.schemas import TaskCreate

    Session = _test_db
    with Session() as s:
        task = tasks_service.create_task(s, TaskCreate(title="Research"))
        sid = task.chat_session_id

    prompt = _build_prompt(sid)
    assert "When web research is blocked" in prompt
    assert "missing Brave API key" in prompt
    assert "403/consent/JavaScript-cookie gates" in prompt
    assert "do not go silent" in prompt
    assert "do not emit an empty response" in prompt
    assert "Tell the user what blocked you" in prompt
    assert "ask how they want to proceed" in prompt


def test_task_prompt_orders_app_context_then_role_then_tools(_test_db, skills_dir: Path):
    from app.tasks import service as tasks_service
    from app.tasks.schemas import TaskCreate

    Session = _test_db
    with Session() as s:
        task = tasks_service.create_task(s, TaskCreate(title="Use tools"))
        sid = task.chat_session_id

    prompt = _build_prompt(sid)
    assert prompt.index("## App context") < prompt.index("## This task")
    assert prompt.index("## This task") < prompt.index("## Inspecting files")
    assert prompt.index("## Inspecting files") < prompt.index("## Work tools")
    assert prompt.index("## Work tools") < prompt.index("## App links")
    assert prompt.index("## Knowledge") < prompt.index("## Skills")


def test_task_prompt_accepts_main_chat_relay(_test_db, skills_dir: Path):
    from app.tasks import service as tasks_service
    from app.tasks.schemas import TaskCreate

    Session = _test_db
    with Session() as s:
        task = tasks_service.create_task(s, TaskCreate(title="Needs input"))
        sid = task.chat_session_id

    prompt = _build_prompt(sid)
    assert "Each terminal move needs a `handoff`" in prompt
    assert "main-chat assistant" in prompt
    assert "relays an answer" in prompt
    assert "relay_to_task" in prompt
    assert "treat it as user intent" in prompt


def test_skills_block_appended_after_knowledge(_test_db, skills_dir: Path):
    """Cache-prefix invariant: skills block lives after the knowledge tree."""
    _write_skill(skills_dir, "z-skill", "tail")

    from app.tasks import service as tasks_service
    from app.tasks.schemas import TaskCreate

    Session = _test_db
    with Session() as s:
        task = tasks_service.create_task(s, TaskCreate(title="T1"))
        sid = task.chat_session_id

    prompt = _build_prompt(sid)
    assert prompt.index("## Knowledge") < prompt.index("## Skills")
    assert prompt.index("## Skills") < prompt.index("<skills>")


def test_system_prompt_skill_entries_carry_real_path(_test_db, skills_dir: Path):
    """Regression for #67: the activation hint must point at the actual
    SKILL.md path of each skill, not a hard-coded `data/skills/<name>/`
    prefix that misses default skills under `backend/defaults/skills/`."""
    _write_skill(skills_dir, "foo", "Does foo.")

    from app.tasks import service as tasks_service
    from app.tasks.schemas import TaskCreate

    Session = _test_db
    with Session() as s:
        task = tasks_service.create_task(s, TaskCreate(title="T1"))
        sid = task.chat_session_id

    prompt = _build_prompt(sid)
    # The rendered entry includes the per-skill path so the agent can
    # read it directly without guessing the root directory.
    assert "foo/SKILL.md" in prompt
    assert "(read " in prompt
    # The old buggy activation snippet must be gone — it sent the agent
    # at `data/skills/<name>/SKILL.md` even for default skills.
    assert "read_file('data/skills/<name>/SKILL.md')" not in prompt
