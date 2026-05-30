from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.saved_task_views.models import SavedTaskView

GroupBy = Literal["none"]
Assignee = Literal["user", "assistant"]
TaskStatus = Literal["open", "scheduled", "waiting", "done"]
DueWindow = Literal["today", "week"]

_ALLOWED_FILTER_KEYS = {"assignee", "statuses", "due"}


class FilterBlob(BaseModel):
    assignee: Assignee | None = None
    statuses: list[TaskStatus] | None = None
    due: DueWindow | None = None


def strip_removed_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    if not filters:
        return {}
    out = dict(filters)
    out.pop("labels", None)
    return out


class SavedTaskViewBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    icon: str | None = Field(default=None, max_length=16)
    filters: dict[str, Any] = Field(default_factory=dict)
    group_by: GroupBy = "none"

    @model_validator(mode="after")
    def _validate_filter_shape(self) -> "SavedTaskViewBase":
        self.filters = strip_removed_filters(self.filters)
        bad = set(self.filters.keys()) - _ALLOWED_FILTER_KEYS
        if bad:
            raise ValueError(f"unknown filter keys: {sorted(bad)}")
        FilterBlob.model_validate(self.filters)
        return self


class SavedTaskViewCreate(SavedTaskViewBase):
    pass


class SavedTaskViewUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    icon: str | None = Field(default=None, max_length=16)
    filters: dict[str, Any] | None = None
    group_by: GroupBy | None = None
    sort_index: int | None = None
    is_default: bool | None = None

    @model_validator(mode="after")
    def _validate_filter_shape(self) -> "SavedTaskViewUpdate":
        if self.filters is not None:
            self.filters = strip_removed_filters(self.filters)
            bad = set(self.filters.keys()) - _ALLOWED_FILTER_KEYS
            if bad:
                raise ValueError(f"unknown filter keys: {sorted(bad)}")
            FilterBlob.model_validate(self.filters)
        return self


class SavedTaskViewRead(SavedTaskViewBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sort_index: int
    is_default: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_row(cls, row: SavedTaskView) -> "SavedTaskViewRead":
        return cls.model_validate(
            {
                "id": row.id,
                "name": row.name,
                "icon": row.icon,
                "filters": strip_removed_filters(row.filters_json),
                "group_by": "none",
                "sort_index": row.sort_index,
                "is_default": row.is_default,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
