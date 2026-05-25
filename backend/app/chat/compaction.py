"""Token-aware compaction for the main chat history.

The naive rolling window broke prompt caching: the prefix shifted every
turn, so every request was a fresh cache miss. Compaction replaces that
with a stable prefix — a single summary message stands in for everything
older than the last few exchanges. Between compactions the prefix is
identical turn-to-turn (cache hit); a compaction event invalidates the
cache once.

Trigger is token-based: when the persisted history exceeds a threshold
(~80k tokens) the older portion is summarized via the configured Z.AI
chat model. Recent message groups are kept verbatim so the model can
react to the live thread without lossy paraphrase.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)


# Character-to-token ratio for English-with-code prose. Slightly
# pessimistic on purpose — we'd rather compact a turn early than miss
# the threshold and ship a 100k prompt.
_CHARS_PER_TOKEN = 4
_PER_MESSAGE_OVERHEAD_TOKENS = 8


SUMMARIZER_SYSTEM_PROMPT = (
    "You are summarizing older conversation between a user and their "
    "personal-assistant agent so the assistant can continue from recent "
    "messages plus this summary. Produce a dense, factual third-person recap "
    "(~600-1000 tokens). Lead with what the user wanted and what the "
    "assistant did. Preserve details needed later: task ids, file paths, "
    "names, decisions, open questions, deadlines, and anything the user said "
    "to remember. Drop pleasantries, repeated tool noise, and anything "
    "redundant with live history. Use bullets only when they materially help."
)


@dataclass
class MessageGroup:
    """An atomic unit of conversation that must compact together.

    A user prompt, an assistant text reply, and a tool-call/tool-return
    exchange each form one group. Splitting a tool-call from its return
    would leave pydantic-ai with an unmatched tool_call_id and the run
    would fail.
    """

    kind: str  # 'system' | 'user' | 'assistant_text' | 'tool_exchange'
    messages: list[ModelMessage] = field(default_factory=list)
    tokens: int = 0


@dataclass
class CompactionResult:
    did_compact: bool
    summary_message: ModelMessage | None
    kept_messages: list[ModelMessage]
    compacted_messages: list[ModelMessage]


def estimate_tokens(messages: Sequence[ModelMessage]) -> int:
    """Char-based token estimate. Cheap, no tokenizer dependency.

    Counts the textual content of every part plus a fixed overhead per
    message for role/structural framing. Tool args and returns are
    sized by their string representation.
    """
    total = 0
    for msg in messages:
        total += _PER_MESSAGE_OVERHEAD_TOKENS
        for part in getattr(msg, "parts", []) or []:
            total += _part_tokens(part)
    return total


def _part_tokens(part: Any) -> int:
    text = _part_text(part)
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _part_text(part: Any) -> str:
    """Best-effort text extraction. Used for both token estimation and
    summarizer input rendering."""
    if isinstance(part, TextPart):
        return part.content or ""
    if isinstance(part, UserPromptPart):
        content = part.content
        if isinstance(content, str):
            return content
        # Sequence of UserContent (text + media). Concatenate text bits.
        chunks: list[str] = []
        for item in content or []:
            if isinstance(item, str):
                chunks.append(item)
            else:
                inner = getattr(item, "text", None)
                if isinstance(inner, str):
                    chunks.append(inner)
        return " ".join(chunks)
    if isinstance(part, SystemPromptPart):
        return part.content or ""
    if isinstance(part, ToolCallPart):
        args = part.args
        if isinstance(args, str):
            args_str = args
        elif args is None:
            args_str = ""
        else:
            try:
                import json

                args_str = json.dumps(args, default=str)
            except Exception:
                args_str = str(args)
        return f"{part.tool_name}({args_str})"
    if isinstance(part, ToolReturnPart):
        try:
            return part.model_response_str()
        except Exception:
            return str(getattr(part, "content", ""))
    return ""


def group_messages(messages: Sequence[ModelMessage]) -> list[MessageGroup]:
    """Walk messages in order, emitting atomic groups.

    Tool-exchange groups span an assistant ModelResponse with one or
    more ToolCallParts plus the trailing ModelRequest(s) that carry
    the matching ToolReturnParts. We extend the group until every
    pending tool_call_id has been resolved.
    """
    groups: list[MessageGroup] = []
    pending_tool_ids: set[str] = set()
    current: MessageGroup | None = None

    for msg in messages:
        if pending_tool_ids:
            # Mid-tool-exchange. Absorb whatever this message brings —
            # tool returns close out call ids; further tool calls open
            # new ones in the same exchange.
            assert current is not None
            current.messages.append(msg)
            current.tokens += estimate_tokens([msg])
            for part in msg.parts or []:
                if isinstance(part, ToolCallPart) and part.tool_call_id:
                    pending_tool_ids.add(part.tool_call_id)
                elif isinstance(part, ToolReturnPart) and part.tool_call_id:
                    pending_tool_ids.discard(part.tool_call_id)
            if not pending_tool_ids:
                groups.append(current)
                current = None
            continue

        kind = _classify(msg)
        if kind == "tool_exchange":
            current = MessageGroup(
                kind="tool_exchange",
                messages=[msg],
                tokens=estimate_tokens([msg]),
            )
            for part in msg.parts or []:
                if isinstance(part, ToolCallPart) and part.tool_call_id:
                    pending_tool_ids.add(part.tool_call_id)
            if not pending_tool_ids:
                # Defensive: a tool-call with no id closes immediately.
                groups.append(current)
                current = None
            continue

        groups.append(MessageGroup(kind=kind, messages=[msg], tokens=estimate_tokens([msg])))

    if current is not None:
        # Unbalanced trail — keep the partial exchange so we never drop
        # a tool call without its return. The compactor still respects
        # group boundaries when slicing.
        groups.append(current)

    return groups


def _classify(msg: ModelMessage) -> str:
    parts = msg.parts or []
    if isinstance(msg, ModelResponse):
        if any(isinstance(p, ToolCallPart) for p in parts):
            return "tool_exchange"
        return "assistant_text"
    if isinstance(msg, ModelRequest):
        if any(isinstance(p, SystemPromptPart) for p in parts) and not any(
            isinstance(p, (UserPromptPart, ToolReturnPart)) for p in parts
        ):
            return "system"
        return "user"
    return "user"


def messages_to_text(messages: Sequence[ModelMessage], *, tool_output_truncate: int = 2000) -> str:
    """Render a message list as plain text suitable for the summarizer."""
    lines: list[str] = []
    for msg in messages:
        for part in msg.parts or []:
            line = _render_part(part, tool_output_truncate=tool_output_truncate)
            if line:
                lines.append(line)
    return "\n\n".join(lines)


def _render_part(part: Any, *, tool_output_truncate: int) -> str:
    if isinstance(part, SystemPromptPart):
        return f"[System]\n{part.content}".strip()
    if isinstance(part, UserPromptPart):
        text = _part_text(part)
        return f"[User]\n{text}".strip()
    if isinstance(part, TextPart):
        return f"[Assistant]\n{part.content}".strip()
    if isinstance(part, ToolCallPart):
        args = part.args
        if isinstance(args, str):
            args_str = args
        elif args is None:
            args_str = ""
        else:
            import json

            try:
                args_str = json.dumps(args, default=str)
            except Exception:
                args_str = str(args)
        return f"[Tool call] {part.tool_name}({args_str})"
    if isinstance(part, ToolReturnPart):
        try:
            body = part.model_response_str()
        except Exception:
            body = str(getattr(part, "content", ""))
        if len(body) > tool_output_truncate:
            body = body[: tool_output_truncate - 1].rstrip() + "…"
        return f"[Tool return: {part.tool_name}]\n{body}".strip()
    return ""


SummarizerFn = Callable[[str], str] | Callable[[str], Awaitable[str]]


def _default_summarizer(text: str) -> str:
    """Sync default summarizer. Uses `Agent.run_sync()`.

    Safe only in fully sync contexts (no running event loop). The
    production path runs inside FastAPI's async handler and uses
    `_default_summarizer_async` via `acompact` instead.
    """
    from pydantic_ai import Agent

    from app.agent import build_chat_model
    from app.agent.usage import default_usage_limits

    summarizer: Agent[None, str] = Agent(
        build_chat_model(),
        system_prompt=SUMMARIZER_SYSTEM_PROMPT,
        output_type=str,
    )
    result = summarizer.run_sync(text, usage_limits=default_usage_limits())
    return result.output


async def _default_summarizer_async(text: str) -> str:
    """Async default summarizer. Uses `await agent.run(...)`.

    Avoids `Agent.run_sync()` so we don't (a) trip on a nested event
    loop when called from FastAPI's async handler and (b) block the
    loop for the multi-second LLM round-trip.
    """
    from pydantic_ai import Agent

    from app.agent import build_chat_model
    from app.agent.usage import default_usage_limits

    summarizer: Agent[None, str] = Agent(
        build_chat_model(),
        system_prompt=SUMMARIZER_SYSTEM_PROMPT,
        output_type=str,
    )
    result = await summarizer.run(text, usage_limits=default_usage_limits())
    return result.output


@dataclass
class _CompactionPlan:
    old_messages: list[ModelMessage]
    kept_messages: list[ModelMessage]
    rendered: str


def _plan_compaction(
    messages: Sequence[ModelMessage],
    *,
    trigger_tokens: int,
    keep_groups: int,
) -> _CompactionPlan | None:
    """Decide whether to compact and slice the message list.

    Returns None if compaction is a noop (under threshold, or recent
    `keep_groups` already exceed the threshold so nothing is droppable).
    Otherwise returns the rendered text + the old/kept slices.
    """
    msgs = list(messages)
    total = estimate_tokens(msgs)
    if total <= trigger_tokens:
        return None

    groups = group_messages(msgs)
    if len(groups) <= keep_groups:
        # Threshold exceeded but nothing safely droppable — recent
        # exchanges alone already blow past it. Punt to the next turn.
        return None

    old_groups = groups[:-keep_groups]
    kept_groups = groups[-keep_groups:]

    old_messages: list[ModelMessage] = []
    for g in old_groups:
        old_messages.extend(g.messages)
    kept_messages: list[ModelMessage] = []
    for g in kept_groups:
        kept_messages.extend(g.messages)

    rendered = messages_to_text(old_messages)
    return _CompactionPlan(
        old_messages=old_messages,
        kept_messages=kept_messages,
        rendered=rendered,
    )


def _noop_result(messages: Sequence[ModelMessage]) -> CompactionResult:
    return CompactionResult(
        did_compact=False,
        summary_message=None,
        kept_messages=list(messages),
        compacted_messages=[],
    )


def _build_result(plan: _CompactionPlan, summary_text: str) -> CompactionResult:
    summary_message = build_summary_message(summary_text.strip())
    return CompactionResult(
        did_compact=True,
        summary_message=summary_message,
        kept_messages=plan.kept_messages,
        compacted_messages=plan.old_messages,
    )


def compact(
    messages: Sequence[ModelMessage],
    *,
    trigger_tokens: int,
    keep_groups: int,
    summarizer: Callable[[str], str] | None = None,
) -> CompactionResult:
    """Synchronous compaction. Tests and other sync entry points.

    Behavior:
    - Under threshold → noop (no summary produced, all messages kept).
    - Over threshold → split groups into [old | recent `keep_groups`].
      Render the old groups as text, hand to `summarizer`, wrap the
      summary via `build_summary_message`, and return summary + recent
      messages as the kept set.

    Use `acompact` instead from inside an async event loop — the
    default summarizer here calls `Agent.run_sync()` and would block
    (or crash on a nested loop).

    See `build_summary_message` for why the summary is wrapped in a
    UserPromptPart with a delimiter rather than a SystemPromptPart.
    """
    plan = _plan_compaction(messages, trigger_tokens=trigger_tokens, keep_groups=keep_groups)
    if plan is None:
        return _noop_result(messages)

    fn: Callable[[str], str] = summarizer if summarizer is not None else _default_summarizer
    return _build_result(plan, fn(plan.rendered))


async def acompact(
    messages: Sequence[ModelMessage],
    *,
    trigger_tokens: int,
    keep_groups: int,
    summarizer: SummarizerFn | None = None,
) -> CompactionResult:
    """Async compaction. Used by the FastAPI request path.

    Same semantics as `compact`, but awaits the LLM call so the event
    loop stays responsive during a compaction event. `summarizer` may
    be sync or async — sync callables are invoked directly, async
    callables are awaited.
    """
    plan = _plan_compaction(messages, trigger_tokens=trigger_tokens, keep_groups=keep_groups)
    if plan is None:
        return _noop_result(messages)

    fn: SummarizerFn = summarizer if summarizer is not None else _default_summarizer_async
    out = fn(plan.rendered)
    if inspect.isawaitable(out):
        out = await out
    return _build_result(plan, out)


def build_summary_message(summary_text: str) -> ModelMessage:
    """Wrap a summary string as a ModelMessage suitable for history.

    UserPromptPart with a clear delimiter: it is unambiguously
    "context, not user input" to the model, but unlike SystemPromptPart
    it stays in the UI-dumped message stream so the user can see what
    the assistant has been told. The UI is responsible for rendering
    the delimiter sensibly; the agent treats it as background context.
    """
    body = (
        "<conversation_summary>\n"
        "Summary of earlier conversation (older messages were compacted "
        "to keep this chat fast). Treat this as background context.\n\n"
        f"{summary_text}\n"
        "</conversation_summary>"
    )
    return ModelRequest(parts=[UserPromptPart(content=body)])
