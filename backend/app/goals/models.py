from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, event, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.datetime_utils import utc_now
from app.db import Base

if TYPE_CHECKING:
    from app.tasks.models import Task


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_done: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tasks: Mapped[list[Task]] = relationship(
        "Task",
        back_populates="goal",
        lazy="selectin",
    )
    events: Mapped[list["GoalEvent"]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by=lambda: (GoalEvent.created_at.desc(), GoalEvent.id.desc()),
    )


class GoalEvent(Base):
    __tablename__ = "goal_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )

    goal: Mapped[Goal] = relationship(back_populates="events")
    task: Mapped[Task | None] = relationship("Task", lazy="selectin")


@event.listens_for(Goal, "before_update")
def _stamp_goal_updated_at(_mapper: object, _connection: object, target: Goal) -> None:
    target.updated_at = utc_now()
