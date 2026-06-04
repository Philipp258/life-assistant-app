"""Owned persistence layer for chat messages.

The DB schema (`app.chat.models.Message` + `MessagePart`) is ours: a
parent message row with ordered, typed part children keyed by a
`part_kind` discriminator. The `mapper` module is the single seam that
translates that schema to/from pydantic-ai's `ModelMessage` types, so the
rest of the app keeps speaking pydantic-ai while nothing external leaks
into the durable store. `tools` adds typed validation for known tool
calls/returns on top of the faithful part payloads.
"""

from app.chat.persist.mapper import (
    build_message_row,
    message_to_pydantic,
    rows_to_pydantic,
    set_message_parts,
)
from app.chat.persist.tools import (
    register_tool_schema,
    typed_tool_args,
    typed_tool_result,
    validate_tool_part,
)
from app.chat.persist import tool_schemas as _tool_schemas  # noqa: F401  (registers defaults on import)

__all__ = [
    "build_message_row",
    "message_to_pydantic",
    "register_tool_schema",
    "rows_to_pydantic",
    "set_message_parts",
    "typed_tool_args",
    "typed_tool_result",
    "validate_tool_part",
]
