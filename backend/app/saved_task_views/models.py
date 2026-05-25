from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SavedTaskView(Base):
    __tablename__ = "saved_task_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # JSON shape:
    #   {"labels": ["home"], "assignee": "user" | "assistant" | null,
    #    "statuses": ["open"], "due": "today" | "week" | null}
    filters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    group_by: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
