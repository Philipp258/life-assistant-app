"""Default arg schemas for the tools whose calls the UI renders.

Registering a schema makes a known tool's persisted args validated on
save (see `app.chat.persist.tools`). Kept permissive (`extra="allow"`)
so a new optional arg never trips a warning — the point is to catch a
genuinely malformed call, not to freeze the signature. Imported by the
persist package so registration happens before any message is saved.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.chat.persist.tools import register_tool_schema


class _Args(BaseModel):
    model_config = ConfigDict(extra="allow")


class CompleteTaskArgs(_Args):
    handoff: str


class ReassignTaskArgs(_Args):
    assignee: str
    handoff: str


class RescheduleTaskArgs(_Args):
    do_at: str
    handoff: str


class AskUserChoiceArgs(_Args):
    question: str
    options: list[str]
    allow_free_text: bool = True


def register_default_tool_schemas() -> None:
    register_tool_schema("complete_task", args=CompleteTaskArgs)
    register_tool_schema("reassign_task", args=ReassignTaskArgs)
    register_tool_schema("reschedule_task", args=RescheduleTaskArgs)
    register_tool_schema("ask_user_choice", args=AskUserChoiceArgs)


register_default_tool_schemas()
