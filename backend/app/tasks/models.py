from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.datetime_utils import utc_now
from app.db import Base

if TYPE_CHECKING:
    from app.goals.models import Goal

IntervalUnit = Literal["hour", "day", "week"]
Assignee = Literal["user", "assistant"]


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "(interval_unit IS NULL) = (interval_count IS NULL)",
            name="ck_tasks_interval_pair",
        ),
        CheckConstraint(
            "interval_count IS NULL OR interval_count >= 1",
            name="ck_tasks_interval_count_positive",
        ),
        CheckConstraint(
            "interval_unit IS NULL OR interval_unit IN ('hour','day','week')",
            name="ck_tasks_interval_unit",
        ),
        CheckConstraint(
            "assignee IN ('user','assistant')",
            name="ck_tasks_assignee",
        ),
    )

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
    assignee: Mapped[Assignee] = mapped_column(
        String(16), nullable=False, default="user", server_default="user"
    )
    # Every task has its own 1-to-1 chat session. The FK is CASCADE in
    # both directions: deleting a task drops its session (and messages);
    # deleting the session also drops the task. Without this, a deleted
    # session would leave a permanently unrunnable task (no chat for the
    # runner to wake, no thread for the detail page to render).
    chat_session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    goal_id: Mapped[int | None] = mapped_column(
        ForeignKey("goals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    do_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    interval_unit: Mapped[IntervalUnit | None] = mapped_column(String(8), nullable=True)
    interval_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Stable identity for a recurring assistant routine's durable log under
    # `data/knowledge/Task Log/<task_log_line>.md`. Set on creation for
    # recurring assistant tasks and copied forward by `_spawn_next_recurrence`
    # so each cycle reads/writes the same log file even though the task row
    # and chat session are fresh. NULL on non-recurring tasks; a paused
    # routine may keep the line while assigned to the user so resuming it
    # does not lose continuity. Titles are editable, so identity can't ride
    # on them.
    task_log_line: Mapped[str | None] = mapped_column(String(128), nullable=True)

    goal: Mapped[Goal | None] = relationship(
        "Goal",
        back_populates="tasks",
        lazy="selectin",
    )

    # Wake-loop health counters. The autonomous runner increments these
    # per wake outcome; recurring task spawn (`_spawn_next_recurrence`)
    # creates a fresh row, so counters always start at 0 for a new cycle.
    consecutive_stalls: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    consecutive_errors: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    consecutive_reschedules: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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
    # Cross-process run-claim. Set (via a direct UPDATE, so it doesn't
    # bump `updated_at`) while a runner is mid-wake on this task; cleared
    # when the wake ends. A *fresh* claim makes the task ineligible for
    # another runner — so a process restart (uvicorn --reload, deploy)
    # whose lifespan recovery re-wakes in-flight tasks cannot run a task
    # the previous still-alive process is executing (which produced two
    # completions / duplicate handoffs). A stale claim (older than the
    # TTL — the prior runner died) is reclaimable.
    run_claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


@event.listens_for(Task, "before_update")
def _stamp_task_updated_at(_mapper: object, _connection: object, target: Task) -> None:
    """Refresh `updated_at` for every ORM-managed task mutation.

    Task rows are updated from several lifecycle owners (tools, runner,
    routers). Keeping the timestamp on the model means those callers no
    longer need to remember separate bookkeeping whenever they change a
    task or its relationships.
    """
    target.updated_at = utc_now()
