"""Wrap tool registrations so unexpected exceptions become structured
tool feedback instead of aborting the assistant turn.

Life Assistant's tool functions already convert their *expected* failure modes
(missing files, validation errors, HTTP non-2xx, etc.) into an
`{"error": "..."}` envelope. But anything they miss — a bad input the
tool's own try/except didn't anticipate, a third-party library that
raises a type we didn't enumerate — bubbles up out of pydantic-ai's
run loop. The Vercel UI adapter then substitutes a stub
`"Tool execution was interrupted by an error."` return part and ends
the turn, so the assistant can neither correct the call nor explain
to the user what happened.

This module installs a thin wrapper over `agent.tool` /
`agent.tool_plain` that catches such exceptions per call and returns
the same `{"error": "..."}` envelope. The model sees the failure as
ordinary tool feedback and the generation continues.

We deliberately pass through:
- `ModelRetry` — pydantic-ai's own "retry the model with this feedback"
  signal. Already turns into a `RetryPromptPart`.
- `asyncio.CancelledError`, `KeyboardInterrupt`, `SystemExit` —
  control-flow / shutdown signals; swallowing them would hang the
  task or mask shutdown.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from typing import Any, Callable

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelRetry

_PASSTHROUGH: tuple[type[BaseException], ...] = (
    ModelRetry,
    asyncio.CancelledError,
    KeyboardInterrupt,
    SystemExit,
)


def _format_error(exc: BaseException) -> dict[str, Any]:
    return {"error": f"{type(exc).__name__}: {exc}"}


def _wrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Return a wrapper that catches uncaught exceptions from `func`.

    `functools.wraps` copies `__wrapped__` and `__annotations__`, which
    is what pydantic-ai's schema introspection (`inspect.signature` +
    `typing.get_type_hints`) reads. So the tool's JSON schema and
    docstring-derived parameter docs survive unchanged.
    """
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except _PASSTHROUGH:
                raise
            except Exception as exc:
                return _format_error(exc)

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except _PASSTHROUGH:
            raise
        except Exception as exc:
            return _format_error(exc)

    return sync_wrapper


def install(agent: Agent[Any, Any]) -> None:
    """Monkey-patch `agent.tool` / `agent.tool_plain` to wrap registrants.

    Idempotent: a second install on the same agent is a no-op.
    Must be called before any tool is registered so every tool added
    via the agent decorators picks up the wrapper.
    """
    if getattr(agent, "_life_assistant_safe_tools_installed", False):
        return

    orig_tool = agent.tool
    orig_tool_plain = agent.tool_plain

    def _patched(orig: Callable[..., Any]) -> Callable[..., Any]:
        def patched(func: Any = None, /, **kwargs: Any) -> Any:
            if func is None:
                # Used as `@agent.tool(...)` — first call returns the real decorator.
                inner = orig(**kwargs)

                def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
                    inner(_wrap(f))
                    return f

                return decorator
            # Used as `@agent.tool` — direct registration.
            orig(_wrap(func))
            return func

        return patched

    agent.tool = _patched(orig_tool)  # type: ignore[method-assign]
    agent.tool_plain = _patched(orig_tool_plain)  # type: ignore[method-assign]
    agent._life_assistant_safe_tools_installed = True  # type: ignore[attr-defined]
