"""Rename the improvement loop from improve-otto -> improve-life-assistant

Product rename (Otto -> Life Assistant). Two pieces of live data still
carry the old slug:

- the `labels` row seeded as `improve-otto` (routines/tasks reference it
  by `label_id` FK, so renaming the row is enough);
- the seeded "Process improvement items" routine, whose `tasks.description`
  brief embeds the literal "`improve-otto` skill" string (from
  `d8a4b9e017c5`) and is replayed into the agent prompt verbatim on every
  wake — it must point at the renamed skill.

Idempotent: no-op when the old slug is absent or already renamed.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1f7a4c20d83"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_SLUG = "improve-otto"
NEW_SLUG = "improve-life-assistant"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE labels SET slug = :new, name = 'Improve the assistant' WHERE slug = :old"
        ).bindparams(old=OLD_SLUG, new=NEW_SLUG)
    )
    op.execute(
        sa.text(
            "UPDATE tasks SET description = REPLACE(description, :old, :new) "
            "WHERE description LIKE :pat"
        ).bindparams(old=OLD_SLUG, new=NEW_SLUG, pat=f"%{OLD_SLUG}%")
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE labels SET slug = :old WHERE slug = :new").bindparams(
            old=OLD_SLUG, new=NEW_SLUG
        )
    )
    op.execute(
        sa.text(
            "UPDATE tasks SET description = REPLACE(description, :new, :old) "
            "WHERE description LIKE :pat"
        ).bindparams(old=OLD_SLUG, new=NEW_SLUG, pat=f"%{NEW_SLUG}%")
    )
