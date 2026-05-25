"""Squashed schema baseline

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-17

Collapses the original 43-migration chain (head 7d8e9f0a1b2c) into one
schema baseline. The DDL below is the *exact* `sqlite_master` output of
that old chain applied to an empty database — replaying it byte-for-byte
guarantees a fresh install gets the schema prod already runs, with no
autogenerate drift (keyset index, CASCADE FKs, CHECK constraints and
server defaults all survive verbatim). See
`tests/fixtures/schema_baseline.sql` for the committed golden snapshot
and `tests/test_baseline_schema.py` for the equivalence guard.

Default routines (weekly reflection, daily consolidation,
improve-life-assistant collect/process, weekly disk-space) are no
longer seeded here — they
moved to the idempotent `app.tasks.default_routines.ensure_default_routines`
called from the FastAPI lifespan. One-time data-repair migrations
(free-chat collapse, label backfill, no-session repair) are dropped:
they only ever mattered for DBs mid-chain, and the one live box is
stamped at this baseline.

Defensive guard: if the `tasks` table already exists the database is
already provisioned (a live box at the old head, or a re-run), so the
upgrade is a no-op that only records this revision. That makes a plain
`alembic upgrade head` correct on both a fresh DB and the live box —
no manual `alembic stamp` required, though it remains a safe fallback.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Exact CREATE TABLE / CREATE INDEX statements emitted by the old
# 43-migration chain (alembic_version is managed by Alembic itself and
# is intentionally omitted). Tables first, then indexes.
_TABLES: tuple[str, ...] = (
    """CREATE TABLE app_settings (
\t"key" VARCHAR(64) NOT NULL,
\tvalue TEXT NOT NULL,
\tcreated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
\tupdated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
\tPRIMARY KEY ("key")
)""",
    """CREATE TABLE labels (
\tid INTEGER NOT NULL,
\tslug VARCHAR(64) NOT NULL,
\tname VARCHAR(120) NOT NULL,
\tdescription TEXT,
\tcolor VARCHAR(32),
\ticon VARCHAR(64),
\tcreated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
\tupdated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
\tPRIMARY KEY (id),
\tCONSTRAINT uq_labels_slug UNIQUE (slug)
)""",
    """CREATE TABLE "messages" (
\tid INTEGER NOT NULL,
\tkind VARCHAR(16) NOT NULL,
\tparts_json JSON NOT NULL,
\tusage_json JSON,
\tmodel_name VARCHAR(128),
\tprovider VARCHAR(64),
\tcreated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
\tsession_id INTEGER NOT NULL,
\tsource_session_id INTEGER, compacted_at DATETIME, archived_at DATETIME,
\tPRIMARY KEY (id),
\tCONSTRAINT fk_messages_session_id_sessions FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE,
\tCONSTRAINT fk_messages_source_session_id_sessions FOREIGN KEY(source_session_id) REFERENCES sessions (id) ON DELETE SET NULL
)""",
    """CREATE TABLE provider_settings (
\tid INTEGER NOT NULL,
\tpreferred_chat_provider VARCHAR(32),
\topenai_api_key TEXT,
\topenai_chat_model VARCHAR(128),
\topenrouter_api_key TEXT,
\topenrouter_chat_model VARCHAR(128),
\tzai_api_key TEXT,
\tzai_endpoint VARCHAR(255),
\tzai_chat_model VARCHAR(128),
\tcodex_auth_json TEXT,
\tcodex_chat_model VARCHAR(128),
\tupdated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, openrouter_tts_model VARCHAR(255), openrouter_tts_voice VARCHAR(128),
\tPRIMARY KEY (id)
)""",
    """CREATE TABLE push_subscriptions (
\tid INTEGER NOT NULL,
\tendpoint VARCHAR NOT NULL,
\tp256dh VARCHAR NOT NULL,
\tauth VARCHAR NOT NULL,
\tuser_agent VARCHAR,
\tcreated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
\tlast_seen_at DATETIME,
\tPRIMARY KEY (id)
)""",
    """CREATE TABLE saved_task_views (
\tid INTEGER NOT NULL,
\tname VARCHAR(120) NOT NULL,
\ticon VARCHAR(16),
\tfilters_json JSON NOT NULL,
\tgroup_by VARCHAR(16) DEFAULT 'none' NOT NULL,
\tsort_index INTEGER DEFAULT '0' NOT NULL,
\tis_default BOOLEAN DEFAULT '0' NOT NULL,
\tcreated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
\tupdated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
\tPRIMARY KEY (id)
)""",
    """CREATE TABLE "sessions" (
\tid INTEGER NOT NULL,
\ttitle VARCHAR(128),
\tcreated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
\ttask_id INTEGER,
\tkind VARCHAR(8) DEFAULT 'task' NOT NULL, event_cursor_id INTEGER,
\tPRIMARY KEY (id),
\tCONSTRAINT ck_sessions_kind CHECK (kind IN ('main', 'agent', 'task')),
\tCONSTRAINT fk_sessions_task_id_tasks FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
)""",
    """CREATE TABLE task_labels (
\tid INTEGER NOT NULL,
\ttask_id INTEGER NOT NULL,
\tlabel_id INTEGER NOT NULL,
\tcreated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
\tPRIMARY KEY (id),
\tFOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE,
\tFOREIGN KEY(label_id) REFERENCES labels (id) ON DELETE CASCADE,
\tCONSTRAINT uq_task_labels_pair UNIQUE (task_id, label_id)
)""",
    """CREATE TABLE "tasks" (
\tid INTEGER NOT NULL,
\ttitle VARCHAR(500) NOT NULL,
\tdescription TEXT,
\tassignee VARCHAR(16) DEFAULT 'user' NOT NULL,
\tdo_at DATETIME,
\tinterval_unit VARCHAR(8),
\tinterval_count INTEGER,
\tcreated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
\tupdated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
\tcompleted_at DATETIME,
\tis_done BOOLEAN DEFAULT 0 NOT NULL,
\tchat_session_id INTEGER NOT NULL,
\tdue_at DATETIME,
\tconsecutive_stalls INTEGER DEFAULT '0' NOT NULL,
\tconsecutive_errors INTEGER DEFAULT '0' NOT NULL,
\tdue_notified_at DATETIME, run_claimed_at DATETIME, consecutive_reschedules INTEGER DEFAULT '0' NOT NULL,
\tPRIMARY KEY (id),
\tCONSTRAINT ck_tasks_interval_count_positive CHECK (interval_count IS NULL OR interval_count >= 1),
\tCONSTRAINT ck_tasks_interval_pair CHECK ((interval_unit IS NULL) = (interval_count IS NULL)),
\tCONSTRAINT ck_tasks_interval_unit CHECK (interval_unit IS NULL OR interval_unit IN ('hour','day','week')),
\tCONSTRAINT ck_tasks_assignee CHECK (assignee IN ('user','assistant')),
\tCONSTRAINT fk_tasks_chat_session_id_sessions FOREIGN KEY(chat_session_id) REFERENCES sessions (id) ON DELETE CASCADE
)""",
    """CREATE TABLE users (
\tid INTEGER NOT NULL,
\tcreated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
\tonboarded_at DATETIME,
\tpassword_hash VARCHAR(255) NOT NULL,
\tPRIMARY KEY (id)
)""",
)

_INDEXES: tuple[str, ...] = (
    "CREATE INDEX ix_messages_archived_at ON messages (archived_at)",
    "CREATE INDEX ix_messages_compacted_at ON messages (compacted_at)",
    "CREATE INDEX ix_messages_created_at ON messages (created_at)",
    "CREATE INDEX ix_messages_session_id ON messages (session_id)",
    "CREATE UNIQUE INDEX ix_push_subscriptions_endpoint ON push_subscriptions (endpoint)",
    "CREATE INDEX ix_sessions_created_at ON sessions (created_at)",
    "CREATE INDEX ix_sessions_kind ON sessions (kind)",
    "CREATE INDEX ix_task_labels_label_id ON task_labels (label_id)",
    "CREATE INDEX ix_task_labels_task_id ON task_labels (task_id)",
    "CREATE INDEX ix_tasks_created_at ON tasks (created_at)",
    "CREATE INDEX ix_tasks_done_completed ON tasks (is_done, completed_at, id)",
    "CREATE INDEX ix_tasks_is_done ON tasks (is_done)",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("tasks"):
        # Already provisioned (live box at the old head, or a re-run):
        # leave the existing schema untouched, just record the revision.
        return
    for stmt in _TABLES:
        op.execute(stmt)
    for stmt in _INDEXES:
        op.execute(stmt)


def downgrade() -> None:
    raise NotImplementedError("0001_baseline is the schema floor; no downgrade.")
