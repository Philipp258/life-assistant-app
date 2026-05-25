"""Add stable seeded-defaults ledger

Revision ID: 2c9f54e0f1a7
Revises: b1f7a4c20d83
Create Date: 2026-05-17

Boot-time routine defaults are keyed by stable code identifiers instead of
mutable user-visible titles. This ledger records that a shipped routine has
been materialized once, so later boots do not duplicate drifted/renamed rows or
resurrect deliberately deleted routines.

Also migrates the old untouched "Today" saved-view seed to the unfiltered
default view shape.
"""

from collections.abc import Sequence
import json
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "2c9f54e0f1a7"
down_revision: Union[str, Sequence[str], None] = "b1f7a4c20d83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROUTINE_BACKFILL: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("weekly-reflection", ("Weekly reflection",)),
    ("daily-consolidation", ("Daily consolidation",)),
    (
        "collect-improvement-items",
        ("Collect improvement items", "Collect improvement opportunities"),
    ),
    ("process-improvement-items", ("Process improvement items",)),
    ("weekly-disk-space-check", ("Weekly disk space check",)),
)

LEGACY_TODAY_FILTERS = {"due": "today", "statuses": ["open", "scheduled"]}
DEFAULT_VIEW_NAME = "Tasks"
DEFAULT_VIEW_FILTERS: dict[str, object] = {}


def _insert_ledger(
    connection: sa.Connection,
    default_type: str,
    default_key: str,
    target_table: str | None,
    target_id: int | None,
) -> None:
    connection.execute(
        sa.text(
            "INSERT OR IGNORE INTO seeded_defaults "
            "(default_type, default_key, target_table, target_id) "
            "VALUES (:default_type, :default_key, :target_table, :target_id)"
        ),
        {
            "default_type": default_type,
            "default_key": default_key,
            "target_table": target_table,
            "target_id": target_id,
        },
    )


def _has_any_row(connection: sa.Connection, table_name: str) -> bool:
    return connection.execute(sa.text(f"SELECT 1 FROM {table_name} LIMIT 1")).first() is not None


def _decode_json(raw: object) -> object:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _migrate_legacy_today_view(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text(
            "SELECT id, icon, filters_json, group_by, sort_index, is_default "
            "FROM saved_task_views WHERE name = :name"
        ),
        {"name": "Today"},
    ).mappings()
    for row in rows:
        try:
            filters = _decode_json(row["filters_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if (
            row["icon"] == "☀️"
            and filters == LEGACY_TODAY_FILTERS
            and row["group_by"] == "none"
            and row["sort_index"] == 0
            and bool(row["is_default"])
        ):
            connection.execute(
                sa.text(
                    "UPDATE saved_task_views "
                    "SET name = :name, icon = NULL, filters_json = :filters_json "
                    "WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "name": DEFAULT_VIEW_NAME,
                    "filters_json": json.dumps(DEFAULT_VIEW_FILTERS),
                },
            )


def upgrade() -> None:
    op.create_table(
        "seeded_defaults",
        sa.Column("default_type", sa.String(length=32), nullable=False),
        sa.Column("default_key", sa.String(length=120), nullable=False),
        sa.Column("target_table", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("default_type", "default_key"),
    )

    connection = op.get_bind()
    tasks = sa.table("tasks", sa.column("id", sa.Integer()), sa.column("title", sa.String()))
    established_install = (
        _has_any_row(connection, "tasks")
        or _has_any_row(connection, "saved_task_views")
        or _has_any_row(connection, "sessions")
        or _has_any_row(connection, "users")
    )
    for default_key, titles in ROUTINE_BACKFILL:
        row = connection.execute(
            sa.select(tasks.c.id).where(tasks.c.title.in_(titles)).order_by(tasks.c.id).limit(1)
        ).first()
        if row is not None:
            _insert_ledger(connection, "task_routine", default_key, "tasks", row.id)
        elif established_install:
            # Existing installs already had the old one-shot routine seeds. If a
            # current default title is absent by the time this migration runs,
            # treat it as deliberately renamed/deleted and tombstone the key.
            _insert_ledger(connection, "task_routine", default_key, None, None)

    _migrate_legacy_today_view(connection)


def downgrade() -> None:
    op.drop_table("seeded_defaults")
