"""Remove task labels.

Revision ID: 8e2f4b7c6a90
Revises: f7b3c9a1d4e2
Create Date: 2026-05-30
"""

from __future__ import annotations

from collections.abc import Sequence
import json
from typing import Any, Union

import sqlalchemy as sa
from alembic import op


revision: str = "8e2f4b7c6a90"
down_revision: Union[str, Sequence[str], None] = "f7b3c9a1d4e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _load_filters(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _strip_saved_view_label_filters() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("saved_task_views"):
        return

    rows = bind.execute(sa.text("SELECT id, filters_json FROM saved_task_views")).mappings()
    for row in rows:
        filters = _load_filters(row["filters_json"])
        if "labels" not in filters:
            continue
        filters.pop("labels", None)
        bind.execute(
            sa.text("UPDATE saved_task_views SET filters_json = :filters WHERE id = :id"),
            {
                "id": row["id"],
                "filters": json.dumps(filters, separators=(",", ":")),
            },
        )


def upgrade() -> None:
    _strip_saved_view_label_filters()

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("task_labels"):
        op.drop_table("task_labels")
    if inspector.has_table("labels"):
        op.drop_table("labels")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("labels"):
        op.create_table(
            "labels",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("color", sa.String(length=32), nullable=True),
            sa.Column("icon", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_labels_slug"),
        )
    if not inspector.has_table("task_labels"):
        op.create_table(
            "task_labels",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("label_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["label_id"], ["labels.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id", "label_id", name="uq_task_labels_pair"),
        )
        op.create_index("ix_task_labels_task_id", "task_labels", ["task_id"])
        op.create_index("ix_task_labels_label_id", "task_labels", ["label_id"])
