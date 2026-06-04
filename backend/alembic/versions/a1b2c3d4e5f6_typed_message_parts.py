"""Typed message schema: parent message + ordered MessagePart children

Revision ID: a1b2c3d4e5f6
Revises: 8e2f4b7c6a90
Create Date: 2026-06-04

Replaces the single `messages.parts_json` blob (an identity dump of
pydantic-ai's wire format) with an owned schema: each message is a parent
row carrying `role`/`instructions`/lifecycle stamps, and its content lives
in ordered `message_parts` children keyed by a `part_kind` discriminator.
The app maps to/from pydantic-ai at the `app.chat.persist` seam.

Chat history is intentionally NOT migrated — there is one single-user box
and the data is disposable at this stage, so the upgrade drops and
recreates `messages` rather than translating old blobs. Sessions, tasks,
and everything else are untouched.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "8e2f4b7c6a90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop child first if a prior partial run left it, then the old parent.
    if _has_table("message_parts"):
        op.drop_table("message_parts")
    op.drop_table("messages")

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("source_session_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("instructions", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("compacted_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("role IN ('request', 'response')", name="ck_messages_role"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_messages_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_session_id"],
            ["sessions.id"],
            name="fk_messages_source_session_id_sessions",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])
    op.create_index("ix_messages_compacted_at", "messages", ["compacted_at"])
    op.create_index("ix_messages_archived_at", "messages", ["archived_at"])

    op.create_table(
        "message_parts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("part_kind", sa.String(length=32), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_message_parts_message_id_messages",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_message_parts_message_id", "message_parts", ["message_id"])
    op.create_index("ix_message_parts_part_kind", "message_parts", ["part_kind"])
    op.create_index("ix_message_parts_tool_call_id", "message_parts", ["tool_call_id"])


def downgrade() -> None:
    op.drop_table("message_parts")
    op.drop_table("messages")
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("source_session_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("parts_json", sa.JSON(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("compacted_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_messages_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_session_id"],
            ["sessions.id"],
            name="fk_messages_source_session_id_sessions",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])
    op.create_index("ix_messages_compacted_at", "messages", ["compacted_at"])
    op.create_index("ix_messages_archived_at", "messages", ["archived_at"])


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)
