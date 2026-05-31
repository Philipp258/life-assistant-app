"""Add durable goals linked to tasks.

Revision ID: f7b3c9a1d4e2
Revises: c8d4e9f2a713
Create Date: 2026-05-29
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "f7b3c9a1d4e2"
down_revision: Union[str, Sequence[str], None] = "c8d4e9f2a713"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("goals"):
        op.create_table(
            "goals",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_done", sa.Boolean(), server_default="0", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = sa.inspect(op.get_bind())
    goal_indexes = {index["name"] for index in inspector.get_indexes("goals")}
    if "ix_goals_created_at" not in goal_indexes:
        op.create_index("ix_goals_created_at", "goals", ["created_at"])
    if "ix_goals_is_done" not in goal_indexes:
        op.create_index("ix_goals_is_done", "goals", ["is_done"])

    task_columns = {column["name"] for column in inspector.get_columns("tasks")}
    if "goal_id" not in task_columns:
        op.execute(
            "ALTER TABLE tasks ADD COLUMN goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL"
        )
    task_indexes = {index["name"] for index in inspector.get_indexes("tasks")}
    if "ix_tasks_goal_id" not in task_indexes:
        op.create_index("ix_tasks_goal_id", "tasks", ["goal_id"])

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("goal_events"):
        op.create_table(
            "goal_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("goal_id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = sa.inspect(op.get_bind())
    event_indexes = {index["name"] for index in inspector.get_indexes("goal_events")}
    if "ix_goal_events_created_at" not in event_indexes:
        op.create_index("ix_goal_events_created_at", "goal_events", ["created_at"])
    if "ix_goal_events_goal_id" not in event_indexes:
        op.create_index("ix_goal_events_goal_id", "goal_events", ["goal_id"])
    if "ix_goal_events_task_id" not in event_indexes:
        op.create_index("ix_goal_events_task_id", "goal_events", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_goal_events_task_id", table_name="goal_events")
    op.drop_index("ix_goal_events_goal_id", table_name="goal_events")
    op.drop_index("ix_goal_events_created_at", table_name="goal_events")
    op.drop_table("goal_events")

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_index("ix_tasks_goal_id")
        batch_op.drop_constraint("fk_tasks_goal_id_goals", type_="foreignkey")
        batch_op.drop_column("goal_id")

    op.drop_index("ix_goals_is_done", table_name="goals")
    op.drop_index("ix_goals_created_at", table_name="goals")
    op.drop_table("goals")
