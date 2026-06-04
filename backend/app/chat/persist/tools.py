"""Typed schemas for persisted tool calls.

Tool calls and returns are persisted faithfully in a part's `payload`, but
for *known* tools we also validate the args (on the call) and the result
(on the return) against a registered Pydantic schema. This is the "schema
for arguments / schema for output" guarantee — a malformed known-tool call
is caught and logged at persist time instead of silently round-tripping.

Validation is non-fatal: a mismatch logs a warning and the part is still
stored faithfully, so a schema drift never kills a live agent turn. Tools
with no registered schema fall back to raw JSON.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class ToolSchema:
    __slots__ = ("args", "result")

    def __init__(self, args: type[BaseModel] | None, result: type[BaseModel] | None) -> None:
        self.args = args
        self.result = result


_REGISTRY: dict[str, ToolSchema] = {}


def register_tool_schema(
    tool_name: str,
    *,
    args: type[BaseModel] | None = None,
    result: type[BaseModel] | None = None,
) -> None:
    """Register arg/result schemas for a tool name. Either may be omitted."""
    _REGISTRY[tool_name] = ToolSchema(args=args, result=result)


def _coerce_args(raw: Any) -> dict[str, Any] | None:
    """pydantic-ai stores tool args as a JSON string or a dict."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def validate_tool_part(part_kind: str, payload: dict[str, Any]) -> None:
    """Best-effort validate a tool-call/tool-return payload against its schema.

    Logs a warning on mismatch; never raises. `payload` is the dumped
    pydantic-ai part dict.
    """
    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        return
    schema = _REGISTRY.get(tool_name)
    if schema is None:
        return
    if part_kind in ("tool-call", "builtin-tool-call") and schema.args is not None:
        data = _coerce_args(payload.get("args"))
        if data is None:
            return
        try:
            schema.args.model_validate(data)
        except ValidationError as exc:
            logger.warning("tool args schema mismatch for %s: %s", tool_name, exc)
    elif part_kind in ("tool-return", "builtin-tool-return") and schema.result is not None:
        content = payload.get("content")
        if not isinstance(content, dict):
            return
        try:
            schema.result.model_validate(content)
        except ValidationError as exc:
            logger.warning("tool result schema mismatch for %s: %s", tool_name, exc)


def typed_tool_args(tool_name: str, raw_args: Any) -> BaseModel | None:
    """Return the validated args model for a known tool, or None."""
    schema = _REGISTRY.get(tool_name)
    if schema is None or schema.args is None:
        return None
    data = _coerce_args(raw_args)
    if data is None:
        return None
    try:
        return schema.args.model_validate(data)
    except ValidationError:
        return None


def typed_tool_result(tool_name: str, raw_content: Any) -> BaseModel | None:
    """Return the validated result model for a known tool, or None."""
    schema = _REGISTRY.get(tool_name)
    if schema is None or schema.result is None:
        return None
    if not isinstance(raw_content, dict):
        return None
    try:
        return schema.result.model_validate(raw_content)
    except ValidationError:
        return None
