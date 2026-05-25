"""Regression tests for the tool-error-feedback wrapper.

When a tool raises an exception its `try/except` didn't anticipate,
the wrapper installed by `app.agent.safe_tools.install` must convert
it into an `{"error": "..."}` envelope and let the agent run continue.
Without the wrapper, pydantic-ai propagates the exception out of the
run loop and the Vercel UI adapter substitutes a stub
`"Tool execution was interrupted by an error."` message — which is
exactly what issue #168 reported for `glob_files` on an absolute
pattern.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo

from app.agent.safe_tools import install as install_safe_tools
from tests._function_model import build_function_model


def _new_agent() -> Agent[None, str]:
    """Bare agent with the safe-tools wrapper installed.

    No deps_type / model — we override the model per test with
    `FunctionModel` and never invoke a real provider.
    """
    agent: Agent[None, str] = Agent("test")
    install_safe_tools(agent)
    return agent


def test_sync_tool_exception_returned_as_error_dict():
    """A sync tool that raises a non-ModelRetry exception must come
    back as `{"error": "..."}` rather than propagating out of the run."""
    agent = _new_agent()

    @agent.tool_plain
    def boom(pattern: str) -> dict:
        """Raise to simulate an uncaught tool failure."""
        raise NotImplementedError(f"Non-relative patterns are unsupported: {pattern}")

    call_count = 0
    captured_tool_result: list[ToolReturnPart] = []

    def handler(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="boom", args={"pattern": "/x/y"}, tool_call_id="t1")]
            )
        # Second turn: capture the tool return part the framework injected.
        for msg in messages:
            for part in getattr(msg, "parts", []):
                if isinstance(part, ToolReturnPart) and part.tool_name == "boom":
                    captured_tool_result.append(part)
        return ModelResponse(parts=[TextPart(content="recovered")])

    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(agent.run("call boom"))

    assert call_count == 2, "the agent should be re-prompted after the tool error"
    assert result.output == "recovered"
    assert len(captured_tool_result) == 1
    payload = captured_tool_result[0].content
    assert isinstance(payload, dict)
    assert "error" in payload
    assert "NotImplementedError" in payload["error"]
    assert "Non-relative patterns" in payload["error"]


def test_async_tool_exception_returned_as_error_dict():
    agent = _new_agent()

    @agent.tool_plain
    async def boom_async(x: int) -> dict:
        """Raise asynchronously."""
        await asyncio.sleep(0)
        raise RuntimeError(f"nope-{x}")

    call_count = 0
    captured: list[ToolReturnPart] = []

    def handler(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="boom_async", args={"x": 7}, tool_call_id="t1")]
            )
        for msg in messages:
            for part in getattr(msg, "parts", []):
                if isinstance(part, ToolReturnPart) and part.tool_name == "boom_async":
                    captured.append(part)
        return ModelResponse(parts=[TextPart(content="ok")])

    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(agent.run("call boom_async"))

    assert result.output == "ok"
    assert len(captured) == 1
    payload = captured[0].content
    assert isinstance(payload, dict)
    assert payload["error"] == "RuntimeError: nope-7"


def test_model_retry_passes_through():
    """`ModelRetry` is pydantic-ai's own retry-the-model signal — the
    wrapper must NOT swallow it into an error dict, or the agent would
    lose the retry flow."""
    agent = _new_agent()

    @agent.tool_plain
    def needs_retry(x: int) -> dict:
        """Always asks for a retry."""
        raise ModelRetry("try again with x>10")

    call_count = 0
    saw_retry_prompt = False

    def handler(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count, saw_retry_prompt
        call_count += 1
        # On the second turn, the framework should have appended a
        # RetryPromptPart carrying our message.
        if call_count == 2:
            from pydantic_ai.messages import RetryPromptPart

            for msg in messages:
                for part in getattr(msg, "parts", []):
                    if isinstance(part, RetryPromptPart) and "try again" in str(part.content):
                        saw_retry_prompt = True
        if call_count == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="needs_retry", args={"x": 1}, tool_call_id="r1")]
            )
        return ModelResponse(parts=[TextPart(content="done")])

    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(agent.run("go"))

    assert result.output == "done"
    assert saw_retry_prompt, "ModelRetry must reach the model as a RetryPromptPart"


def test_cancellederror_passes_through():
    """asyncio.CancelledError must propagate so task cancellation works.

    The wrapper exists to surface routine errors as feedback — not to
    swallow shutdown / cancellation signals.
    """
    from app.agent import safe_tools

    @safe_tools._wrap
    def cancelled() -> dict:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        cancelled()


def test_wrapper_preserves_signature_and_annotations_for_schema():
    """pydantic-ai's schema generator reads `inspect.signature` (follows
    `__wrapped__`) and `__annotations__` from the registered function.
    `functools.wraps` carries both — verify it didn't regress."""
    from app.agent import safe_tools

    def original(path: str, limit: int = 10) -> dict:
        """Doc line."""
        return {"path": path, "limit": limit}

    wrapped = safe_tools._wrap(original)
    assert wrapped.__doc__ == "Doc line."
    assert wrapped.__name__ == "original"

    sig = inspect.signature(wrapped)
    assert list(sig.parameters) == ["path", "limit"]
    assert sig.parameters["limit"].default == 10
    # get_type_hints reads `__annotations__` from the wrapper — which
    # functools.wraps copies from `original` — not from the wrapper's
    # own *args/**kwargs signature.
    from typing import get_type_hints

    hints = get_type_hints(wrapped)
    assert hints["path"] is str
    assert hints["limit"] is int


def test_install_is_idempotent():
    """Calling install twice on the same agent must not double-wrap."""
    agent: Agent[None, str] = Agent("test")
    install_safe_tools(agent)
    first = agent.tool_plain
    install_safe_tools(agent)
    assert agent.tool_plain is first


def test_glob_files_absolute_pattern_returns_error_to_model(_test_db):
    """End-to-end regression for the exact issue #168 case.

    `glob_files({"pattern": "/opt/life-assistant/..."})` triggers a
    `NotImplementedError` from `Path.glob` (Python 3.11+ refuses
    absolute glob patterns). With the wrapper installed on the real
    agent, the tool result must be an `{"error": "..."}` dict that
    reaches the model — not a crashed turn that the UI papers over
    with "Tool execution was interrupted by an error."
    """
    from app.agent import get_agent, invalidate_agent

    # The cached agent may have been built without the wrapper in
    # earlier test sessions; rebuild fresh.
    invalidate_agent()
    agent = get_agent()

    call_count = 0
    captured: list[ToolReturnPart] = []

    def handler(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="glob_files",
                        args={"pattern": "/opt/life-assistant/.github/workflows/*.yml"},
                        tool_call_id="g1",
                    )
                ]
            )
        for msg in messages:
            for part in getattr(msg, "parts", []):
                if isinstance(part, ToolReturnPart) and part.tool_name == "glob_files":
                    captured.append(part)
        return ModelResponse(parts=[TextPart(content="ack")])

    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(agent.run("find me yamls"))

    assert call_count == 2
    assert result.output == "ack"
    assert len(captured) == 1
    payload = captured[0].content
    assert isinstance(payload, dict)
    assert "error" in payload
    # The exact error class differs across Python versions
    # (NotImplementedError on 3.11/3.12, ValueError on 3.13+). The
    # wrapper labels the class name, so just check it isn't the
    # pydantic-ai UI stub.
    assert "Tool execution was interrupted" not in payload["error"]
    # Clean up the cached agent so we don't poison later tests.
    invalidate_agent()
