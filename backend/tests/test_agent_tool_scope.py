from __future__ import annotations

import asyncio

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo

from app.agent.deps import AgentDeps
from app.chat.service import get_or_create_main_session
from app.tasks.schemas import TaskCreate
from tests._function_model import build_function_model


# Inspect tools (read-only, local, instant) stay available everywhere —
# main chat needs to look at the repo to scope and ground its answers.
INSPECT_TOOLS = {
    "read_file",
    "glob_files",
    "grep",
}

# Act tools (mutate the repo or reach out over the network) are task-only:
# main chat delegates this kind of work instead of doing it inline.
ACT_TOOLS = {
    "bash",
    "write_file",
    "edit_file",
    "web_search",
    "web_fetch",
}

COORDINATION_TOOLS = {
    "create_task",
    "list_tasks",
    "get_task",
    "update_task",
    "delete_task",
    "relay_to_task",
    "list_chat_messages",
    "search_main_chat_history",
    "read_knowledge",
    "save_knowledge",
    "save_core_memory",
    "get_app_settings",
    "set_app_setting",
}


def _task_session_id() -> int:
    from app.db import SessionLocal
    from app.tasks import service as tasks_service

    with SessionLocal() as db:
        task = tasks_service.create_task(
            db,
            TaskCreate(
                title="Inspect repository",
                description="Use raw work tools.",
                assignee="assistant",
            ),
        )
        return task.chat_session_id


def _main_session_id() -> int:
    from app.db import SessionLocal

    with SessionLocal() as db:
        return get_or_create_main_session(db).id


def _tools_visible_to_model(session_id: int) -> set[str]:
    from app.agent import get_agent, invalidate_agent

    invalidate_agent()
    captured: set[str] = set()

    def handler(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        captured.update(tool.name for tool in info.function_tools)
        return ModelResponse(parts=[TextPart(content="ok")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(agent.run("list tools", deps=AgentDeps(session_id=session_id)))

    assert result.output == "ok"
    return captured


def test_main_chat_keeps_inspect_and_coordination_tools_but_hides_act_tools(_test_db):
    visible = _tools_visible_to_model(_main_session_id())

    assert INSPECT_TOOLS <= visible
    assert COORDINATION_TOOLS <= visible
    assert visible.isdisjoint(ACT_TOOLS)


def test_task_chat_keeps_inspect_and_act_tools(_test_db):
    visible = _tools_visible_to_model(_task_session_id())

    assert (INSPECT_TOOLS | ACT_TOOLS) <= visible


def test_main_chat_act_tool_call_cannot_execute(_test_db, monkeypatch):
    from app.agent import get_agent, invalidate_agent
    from app.agent.tools import shell as shell_tools

    invalidate_agent()
    called = False

    def fake_bash(command: str, timeout: int = 120) -> dict[str, object]:
        nonlocal called
        called = True
        return {"stdout": command, "stderr": "", "exit_code": 0, "timed_out": False}

    monkeypatch.setattr(shell_tools, "do_bash", fake_bash)

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="bash",
                    args={"command": "echo should-not-run"},
                    tool_call_id="blocked",
                )
            ]
        )

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        with pytest.raises(UnexpectedModelBehavior):
            asyncio.run(agent.run("try bash", deps=AgentDeps(session_id=_main_session_id())))

    assert called is False
