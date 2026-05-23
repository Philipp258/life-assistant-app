"""Move assistant name out of behavior.md into app_settings

Revision ID: 9c1de4f7b201
Revises: 3a4f8c2e7d10
Create Date: 2026-05-23

Assistant identity (name) used to live as a regex-parsed first line in
`data/core/behavior.md`. We now treat it as structured data in the
``app_settings`` whitelist alongside ``user_name``. This migration is a
one-shot: parse the existing line out of behavior.md, insert the value
into ``app_settings``, and strip the line (plus any immediately following
blank lines) from the file so the markdown becomes pure prose.

The companion identity field ``user_name`` has no historical convention
to parse from, so it is left unset; the operator backfills via
``python -m app.knowledge.set_name --user <name>`` (or
``PATCH /api/identity``) after deploy.
"""

from __future__ import annotations

from collections.abc import Sequence
import logging
from pathlib import Path
import re
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "9c1de4f7b201"
down_revision: Union[str, Sequence[str], None] = "3a4f8c2e7d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAME_RE = re.compile(r"^\s*\*\*Name:\*\*\s+(.+?)\s*$")
SCAN_LINES = 8
ASSISTANT_NAME_KEY = "assistant_name"

log = logging.getLogger("alembic.runtime.migration")


def _parse_and_strip(text: str) -> tuple[str | None, str]:
    lines = text.splitlines(keepends=True)
    for idx, raw in enumerate(lines[:SCAN_LINES]):
        m = NAME_RE.match(raw.rstrip("\n").rstrip("\r"))
        if not m:
            continue
        name = m.group(1).strip()
        end = idx + 1
        while end < len(lines) and lines[end].strip() == "":
            end += 1
        rewritten = "".join(lines[:idx] + lines[end:])
        return name, rewritten
    return None, text


def apply_to(connection: sa.Connection, behavior_path: Path) -> str | None:
    """One-shot migration body, exposed so tests can drive it with their
    own connection and filesystem layout. Returns the imported name (or
    ``None`` if no name line was present).
    """
    if not behavior_path.is_file():
        return None

    original = behavior_path.read_text(encoding="utf-8")
    name, rewritten = _parse_and_strip(original)
    if name is None:
        return None

    connection.execute(
        sa.text(
            "INSERT OR IGNORE INTO app_settings (key, value, created_at, updated_at) "
            "VALUES (:key, :value, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"key": ASSISTANT_NAME_KEY, "value": name},
    )

    if rewritten != original:
        behavior_path.write_text(rewritten, encoding="utf-8")

    return name


def upgrade() -> None:
    from app.config import CORE_DIR

    name = apply_to(op.get_bind(), CORE_DIR / "behavior.md")
    if name is not None:
        log.info(
            "identity migration: imported assistant_name=%r from behavior.md; "
            "user_name remains unset until operator runs "
            "`python -m app.knowledge.set_name --user <name>`.",
            name,
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM app_settings WHERE key = :key"),
        {"key": ASSISTANT_NAME_KEY},
    )
