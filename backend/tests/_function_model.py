"""Streaming-compatible `FunctionModel` factory for tests.

The runner now passes `event_stream_handler` to `agent.run` so that
pydantic-ai routes through the streaming HTTP path (required by
Codex's Responses endpoint, which rejects non-streaming requests for
some models). That makes plain `FunctionModel(handler)` mocks fail with
"FunctionModel must receive a `stream_function` to support streamed
requests".

`build_function_model` wraps the existing non-streaming handler into a
stream function so test handlers that return a single `ModelResponse`
keep working without rewriting each one as an async generator.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable, Union

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    FunctionModel,
)


HandlerResult = Union[ModelResponse, Awaitable[ModelResponse]]
Handler = Callable[[list[ModelMessage], AgentInfo], HandlerResult]


def build_function_model(handler: Handler) -> FunctionModel:
    """Return a `FunctionModel` with both streaming and non-streaming paths.

    The non-streaming path delegates straight to `handler`. The streaming
    path calls `handler` once and emits its `ModelResponse` parts as a
    sequence of stream items (`str` for text, `DeltaToolCall` for tool
    calls), matching the format `FunctionStreamedResponse` consumes.
    """

    async def stream_function(messages, info):
        result = handler(messages, info)
        if hasattr(result, "__await__"):
            response = await result
        else:
            response = result

        for index, part in enumerate(response.parts):
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                args = part.args
                if isinstance(args, str):
                    json_args = args
                else:
                    json_args = json.dumps(args)
                yield {
                    index: DeltaToolCall(
                        name=part.tool_name,
                        json_args=json_args,
                        tool_call_id=part.tool_call_id,
                    )
                }
            else:
                raise NotImplementedError(
                    f"build_function_model: unsupported part type {type(part).__name__}"
                )

    return FunctionModel(function=handler, stream_function=stream_function)
