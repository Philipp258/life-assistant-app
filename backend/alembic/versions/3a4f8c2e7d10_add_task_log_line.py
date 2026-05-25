"""Add task_log_line column + backfill existing recurring assistant routines

Revision ID: 3a4f8c2e7d10
Revises: 2c9f54e0f1a7
Create Date: 2026-05-21

`task_log_line` is the stable identity for a recurring assistant routine's
durable log under `data/knowledge/Task Log/<line>.md`. Set on creation by
the service layer and copied forward by `_spawn_next_recurrence`; titles
remain editable and are not used as identity.

This migration adds the nullable column and backfills it for every
existing recurring assistant task. The backfill slug is derived from the
current title. Historical cycles that slugify to the same string share
one line when there is at most one active row, so an existing routine
does not start future cycles on `weekly-reflection-17` just because it
has sixteen completed predecessors. Multiple active rows with the same
slug are disambiguated with `-2`, `-3`, … because they may be separate
live routines. Non-recurring tasks and user-owned tasks are left NULL.
"""

from collections.abc import Sequence
import re
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "3a4f8c2e7d10"
down_revision: Union[str, Sequence[str], None] = "2c9f54e0f1a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SLUG_NONALNUM = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LEN = 96


def _slugify(title: str) -> str:
    s = (title or "").strip().lower()
    s = _SLUG_NONALNUM.sub("-", s)
    s = s.strip("-")
    if len(s) > _MAX_SLUG_LEN:
        s = s[:_MAX_SLUG_LEN].rstrip("-")
    return s or "routine"


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("task_log_line", sa.String(length=128), nullable=True),
    )

    connection = op.get_bind()
    # Recurring assistant tasks only. Historical cycles with the same
    # slug normally share one line; multiple active same-slug rows are
    # treated as ambiguous live routines and split. NULL
    # interval_unit/interval_count -> not recurring.
    rows = (
        connection.execute(
            sa.text(
                "SELECT id, title, is_done FROM tasks "
                "WHERE assignee = 'assistant' "
                "  AND interval_unit IS NOT NULL "
                "  AND interval_count IS NOT NULL "
                "ORDER BY id"
            )
        )
        .mappings()
        .all()
    )

    taken: set[str] = set()
    rows_by_base = {}
    for row in rows:
        rows_by_base.setdefault(_slugify(row["title"]), []).append(row)

    def fresh_line(base: str) -> str:
        candidate = base
        suffix = 2
        while candidate in taken:
            candidate = f"{base}-{suffix}"
            suffix += 1
        taken.add(candidate)
        return candidate

    for base, base_rows in rows_by_base.items():
        active_rows = [row for row in base_rows if not bool(row["is_done"])]
        if len(active_rows) <= 1:
            line = fresh_line(base)
            for row in base_rows:
                connection.execute(
                    sa.text("UPDATE tasks SET task_log_line = :line WHERE id = :id"),
                    {"line": line, "id": row["id"]},
                )
            continue

        for row in base_rows:
            line = fresh_line(base)
            connection.execute(
                sa.text("UPDATE tasks SET task_log_line = :line WHERE id = :id"),
                {"line": line, "id": row["id"]},
            )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("task_log_line")
