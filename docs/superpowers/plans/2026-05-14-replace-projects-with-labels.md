# Replace Projects with Labels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the rigid one-task-one-project model from Life Assistant. Replace it with multi-label task tagging so cross-cutting saved views (home / review / coding) can be expressed naturally. Existing `inbox` / `improve-otto` / user-created projects become labels with the same slug/name.

**Architecture:** A new `labels` table replaces `projects`. Tasks join to labels through `task_labels` (many-to-many). One Alembic revision creates the new tables, backfills label rows from existing projects (one label per project, copying slug + name + icon + color), copies each task's `project_id` into a row in `task_labels`, then drops `tasks.project_id` and `projects` entirely. The Projects screen + API disappear; a simple Labels CRUD takes its place. The task list keeps working — the only UX regression is no per-project filter (Plan 2 introduces saved views to fill this in).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic (SQLite + batch ops for column drops), pytest. Frontend: React 18, TS, Vitest.

**Out of scope (covered by later plans):**
- Saved task views and tab UI — Plan 2 (`2026-05-14-saved-task-views.md`).
- LLM-driven icon picking — Plan 3 (`2026-05-14-llm-emoji-pick-for-views.md`).

**File map**

Created:
- `backend/app/labels/__init__.py`
- `backend/app/labels/models.py` — `Label`, `TaskLabel` ORM models.
- `backend/app/labels/schemas.py` — `LabelCreate`, `LabelRead`, `LabelUpdate`.
- `backend/app/labels/service.py` — CRUD + lookups.
- `backend/app/labels/router.py` — `/api/labels` endpoints.
- `backend/alembic/versions/<id>_replace_projects_with_labels.py` — schema + data migration.
- `backend/tests/test_labels_router.py`
- `backend/tests/test_tasks_label_filter.py`
- `backend/tests/test_migration_labels_backfill.py`
- `frontend/src/screens/Labels/labelsApi.ts`
- `frontend/src/screens/Labels/ManageLabelsSheet.tsx`
- `frontend/src/screens/Labels/ManageLabelsSheet.test.tsx`

Modified:
- `backend/app/tasks/models.py` — drop `project_id`, add `labels` relationship.
- `backend/app/tasks/schemas.py` — drop `project_id`, add `labels: list[str]`.
- `backend/app/tasks/service.py` — accept/persist labels, replace project filter with label filter.
- `backend/app/tasks/router.py` — drop `project_id` query param, add `?label=<slug>` (repeatable).
- `backend/app/main.py` — register labels router, remove projects router.
- `backend/app/agent/tools/tasks.py` — replace `project_id` arg/refs with `labels`.
- `frontend/src/screens/Tasks/tasksApi.ts` — `Task.labels: string[]`, drop `project_id`.
- `frontend/src/screens/Tasks/TasksScreen.tsx` — drop projects state + ManageProjectsSheet wiring.
- `frontend/src/screens/Tasks/TaskRow.tsx` — drop `projectLabel` prop and chip render.
- `frontend/src/screens/Tasks/NewTaskSheet.tsx` — labels picker instead of project select.
- `frontend/src/screens/Tasks/EditTaskSheet.tsx` — same.
- `frontend/src/screens/Tasks/TaskDetailPage.tsx` — show labels, no project line.
- `frontend/src/screens/Tasks/TasksScreen.test.tsx` — update fixtures.

Deleted:
- `backend/app/projects/` (entire package).
- `frontend/src/screens/Projects/` (entire package).

---

### Task 1: Add Label / TaskLabel ORM models

**Files:**
- Create: `backend/app/labels/__init__.py`
- Create: `backend/app/labels/models.py`

- [ ] **Step 1: Create empty package init**

```python
# backend/app/labels/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_labels_models.py`:

```python
from app.labels.models import Label, TaskLabel


def test_label_table_name():
    assert Label.__tablename__ == "labels"


def test_task_label_table_name():
    assert TaskLabel.__tablename__ == "task_labels"


def test_label_has_slug_unique():
    slug_col = Label.__table__.c.slug
    assert slug_col.unique is True
```

- [ ] **Step 3: Run it, watch it fail**

```bash
cd backend && uv run pytest tests/test_labels_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.labels.models'`.

- [ ] **Step 4: Implement the models**

```python
# backend/app/labels/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Label(Base):
    """A tag applied to zero or more tasks. Replaces the prior Project concept."""

    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class TaskLabel(Base):
    """Join row — a task carries N labels."""

    __tablename__ = "task_labels"
    __table_args__ = (
        UniqueConstraint("task_id", "label_id", name="uq_task_labels_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label_id: Mapped[int] = mapped_column(
        ForeignKey("labels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
```

- [ ] **Step 5: Tests pass**

```bash
cd backend && uv run pytest tests/test_labels_models.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/labels/__init__.py backend/app/labels/models.py backend/tests/test_labels_models.py
git commit -m "feat(labels): add Label and TaskLabel ORM models"
```

---

### Task 2: Alembic migration — create tables, backfill, drop projects

**Files:**
- Create: `backend/alembic/versions/<rev>_replace_projects_with_labels.py`
- Create: `backend/tests/test_migration_labels_backfill.py`

- [ ] **Step 1: Generate revision skeleton**

```bash
cd backend && uv run alembic revision -m "replace projects with labels"
```

Note the generated revision id (`<rev>`). Verify `down_revision = "a3f9e2d6c7b8"` — the current head when this plan was written. If the head has moved on `main`, set `down_revision` to the actual current head.

- [ ] **Step 2: Write the backfill test first**

Create `backend/tests/test_migration_labels_backfill.py`:

```python
"""End-to-end test that the labels migration preserves task→project assignments.

Drives Alembic against a temp SQLite file: stamps `a3f9e2d6c7b8`, inserts a
couple of projects and tasks, upgrades to head, then verifies labels and
task_labels reflect what was in projects.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


@pytest.fixture()
def alembic_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, str]:
    db_path = tmp_path / "migrate.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg, url


def test_migration_copies_projects_to_labels(alembic_cfg):
    cfg, url = alembic_cfg
    command.upgrade(cfg, "a3f9e2d6c7b8")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO projects (slug, name, system) VALUES ('inbox', 'Inbox', 1)"))
        conn.execute(text("INSERT INTO projects (slug, name, system) VALUES ('travel', 'Travel', 0)"))
        conn.execute(text(
            "INSERT INTO tasks (title, project_id, is_done, assignee) "
            "VALUES ('a', 1, 0, 'user'), ('b', 2, 0, 'user')"
        ))

    command.upgrade(cfg, "head")

    with engine.begin() as conn:
        labels = {row.slug: row.id for row in conn.execute(text("SELECT id, slug FROM labels"))}
        assert set(labels.keys()) == {"inbox", "travel"}
        pairs = conn.execute(
            text(
                "SELECT t.title, l.slug FROM tasks t "
                "JOIN task_labels tl ON tl.task_id = t.id "
                "JOIN labels l ON l.id = tl.label_id "
                "ORDER BY t.title"
            )
        ).all()
        assert [(p.title, p.slug) for p in pairs] == [("a", "inbox"), ("b", "travel")]

        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(tasks)"))}
        assert "project_id" not in cols
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert "projects" not in tables
```

- [ ] **Step 3: Run it, watch it fail**

```bash
cd backend && uv run pytest tests/test_migration_labels_backfill.py -v
```

Expected: failure — the migration body is still empty so `task_labels` and `labels` won't exist after upgrade.

- [ ] **Step 4: Implement the migration**

Open the generated file and replace its body with:

```python
"""replace projects with labels

Revision ID: <rev>
Revises: a3f9e2d6c7b8
Create Date: 2026-05-14 ...
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "<rev>"
down_revision = "a3f9e2d6c7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("icon", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_labels_slug"),
    )
    op.create_table(
        "task_labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("label_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["label_id"], ["labels.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("task_id", "label_id", name="uq_task_labels_pair"),
    )
    op.create_index("ix_task_labels_task_id", "task_labels", ["task_id"])
    op.create_index("ix_task_labels_label_id", "task_labels", ["label_id"])

    # Backfill: one label per existing project, then mirror task→project as
    # task→label. We copy slug/name/description/color/icon; system/archived
    # flags do not survive — labels have no system/archived axis.
    op.execute(
        """
        INSERT INTO labels (slug, name, description, color, icon, created_at, updated_at)
        SELECT slug, name, description, color, icon, created_at, updated_at
        FROM projects
        """
    )
    op.execute(
        """
        INSERT INTO task_labels (task_id, label_id, created_at)
        SELECT t.id, l.id, CURRENT_TIMESTAMP
        FROM tasks t
        JOIN projects p ON p.id = t.project_id
        JOIN labels l ON l.slug = p.slug
        """
    )

    # SQLite requires batch_alter_table to drop columns. The FK on
    # tasks.project_id is implicit in the table definition.
    with op.batch_alter_table("tasks") as batch:
        batch.drop_index("ix_tasks_project_id")
        batch.drop_column("project_id")

    op.drop_table("projects")


def downgrade() -> None:
    # Recreating projects from labels is lossy (system/archived flags are
    # gone). We refuse to downgrade rather than silently lose data.
    raise NotImplementedError(
        "Downgrade not supported — projects table cannot be reconstructed. "
        "Restore from backup if you need pre-labels state."
    )
```

- [ ] **Step 5: Tests pass**

```bash
cd backend && uv run pytest tests/test_migration_labels_backfill.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Verify `alembic heads` shows single head**

```bash
cd backend && uv run alembic heads
```

Expected: one line ending `(head)`.

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/<rev>_replace_projects_with_labels.py backend/tests/test_migration_labels_backfill.py
git commit -m "feat(labels): migration creates labels + task_labels, backfills from projects, drops projects"
```

---

### Task 3: Label schemas

**Files:**
- Create: `backend/app/labels/schemas.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_labels_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from app.labels.schemas import LabelCreate, LabelRead


def test_label_create_requires_slug_and_name():
    label = LabelCreate(slug="travel", name="Travel")
    assert label.slug == "travel"
    assert label.name == "Travel"


def test_label_create_rejects_uppercase_slug():
    with pytest.raises(ValidationError):
        LabelCreate(slug="Travel", name="Travel")


def test_label_create_rejects_space_in_slug():
    with pytest.raises(ValidationError):
        LabelCreate(slug="my label", name="My label")


def test_label_read_validates_from_attributes():
    class Stub:
        id = 1
        slug = "x"
        name = "X"
        description = None
        color = None
        icon = None
        created_at = "2026-05-14T00:00:00"
        updated_at = "2026-05-14T00:00:00"
    LabelRead.model_validate(Stub(), from_attributes=True)
```

- [ ] **Step 2: Run it, watch it fail**

```bash
cd backend && uv run pytest tests/test_labels_schemas.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement schemas**

```python
# backend/app/labels/schemas.py
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class LabelBase(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    color: str | None = Field(default=None, max_length=32)
    icon: str | None = Field(default=None, max_length=64)

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, value: str) -> str:
        if not SLUG_RE.fullmatch(value):
            raise ValueError("slug must be lowercase kebab (a-z, 0-9, '-')")
        return value


class LabelCreate(LabelBase):
    pass


class LabelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    color: str | None = Field(default=None, max_length=32)
    icon: str | None = Field(default=None, max_length=64)


class LabelRead(LabelBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Tests pass**

```bash
cd backend && uv run pytest tests/test_labels_schemas.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/labels/schemas.py backend/tests/test_labels_schemas.py
git commit -m "feat(labels): add pydantic schemas with slug validation"
```

---

### Task 4: Label service + CRUD router

**Files:**
- Create: `backend/app/labels/service.py`
- Create: `backend/app/labels/router.py`
- Create: `backend/tests/test_labels_router.py`

- [ ] **Step 1: Write the router tests first**

```python
# backend/tests/test_labels_router.py
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_create_then_list_label():
    resp = client.post("/api/labels", json={"slug": "lab-1", "name": "Lab 1"})
    assert resp.status_code == 201, resp.text
    label_id = resp.json()["id"]

    listing = client.get("/api/labels").json()["labels"]
    assert any(item["id"] == label_id and item["slug"] == "lab-1" for item in listing)


def test_create_label_duplicate_slug_returns_409():
    client.post("/api/labels", json={"slug": "dup", "name": "Dup A"})
    resp = client.post("/api/labels", json={"slug": "dup", "name": "Dup B"})
    assert resp.status_code == 409


def test_patch_label_name():
    created = client.post("/api/labels", json={"slug": "rn-1", "name": "Old"}).json()
    resp = client.patch(f"/api/labels/{created['id']}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


def test_delete_label_clears_join_rows():
    label = client.post("/api/labels", json={"slug": "del-1", "name": "Del"}).json()
    task = client.post(
        "/api/tasks",
        json={"title": "x", "labels": ["del-1"]},
    ).json()
    resp = client.delete(f"/api/labels/{label['id']}")
    assert resp.status_code == 204
    after = client.get(f"/api/tasks/{task['id']}").json()
    assert after["labels"] == []
```

- [ ] **Step 2: Run them, watch them fail**

```bash
cd backend && uv run pytest tests/test_labels_router.py -v
```

Expected: 404s — routes don't exist yet.

- [ ] **Step 3: Implement service**

```python
# backend/app/labels/service.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.labels.models import Label
from app.labels.schemas import LabelCreate, LabelUpdate


class DuplicateSlugError(ValueError):
    pass


def list_labels(session: Session) -> list[Label]:
    return list(session.scalars(select(Label).order_by(Label.name)))


def get_label(session: Session, label_id: int) -> Label | None:
    return session.get(Label, label_id)


def get_label_by_slug(session: Session, slug: str) -> Label | None:
    return session.scalars(select(Label).where(Label.slug == slug)).first()


def create_label(session: Session, body: LabelCreate) -> Label:
    label = Label(**body.model_dump())
    session.add(label)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateSlugError(f"slug '{body.slug}' already exists") from exc
    session.refresh(label)
    return label


def update_label(session: Session, label_id: int, body: LabelUpdate) -> Label | None:
    label = session.get(Label, label_id)
    if label is None:
        return None
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(label, field, value)
    session.commit()
    session.refresh(label)
    return label


def delete_label(session: Session, label_id: int) -> bool:
    label = session.get(Label, label_id)
    if label is None:
        return False
    session.delete(label)  # cascade deletes task_labels rows
    session.commit()
    return True
```

- [ ] **Step 4: Implement router**

```python
# backend/app/labels/router.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.db import SessionLocal
from app.labels import service
from app.labels.schemas import LabelCreate, LabelRead, LabelUpdate

router = APIRouter()


@router.get("/labels")
def list_labels() -> dict[str, list[LabelRead]]:
    with SessionLocal() as session:
        rows = service.list_labels(session)
        return {"labels": [LabelRead.model_validate(label) for label in rows]}


@router.post("/labels", status_code=status.HTTP_201_CREATED)
def create_label(body: LabelCreate) -> LabelRead:
    with SessionLocal() as session:
        try:
            label = service.create_label(session, body)
        except service.DuplicateSlugError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return LabelRead.model_validate(label)


@router.patch("/labels/{label_id}")
def update_label(label_id: int, body: LabelUpdate) -> LabelRead:
    with SessionLocal() as session:
        label = service.update_label(session, label_id, body)
        if label is None:
            raise HTTPException(status_code=404, detail="Label not found")
        return LabelRead.model_validate(label)


@router.delete("/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_label(label_id: int) -> Response:
    with SessionLocal() as session:
        if not service.delete_label(session, label_id):
            raise HTTPException(status_code=404, detail="Label not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 5: Register router in main**

Edit `backend/app/main.py`. Add to imports near `tasks_router`:

```python
from app.labels.router import router as labels_router
```

Add to the `include_router` block right after the tasks line (don't delete the projects line yet — Task 8 does that):

```python
app.include_router(labels_router, prefix="/api")
```

- [ ] **Step 6: Tests pass**

```bash
cd backend && uv run pytest tests/test_labels_router.py -v
```

Expected: 4 passed (note: `test_delete_label_clears_join_rows` depends on Task 5+6 — mark `xfail` for now or skip until then, then re-enable in Task 6 Step 6).

**Action:** Add `@pytest.mark.xfail(reason="task labels persistence lands in Task 5")` decorator to `test_delete_label_clears_join_rows` and `@pytest.fixture` clean up between tests if needed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/labels/service.py backend/app/labels/router.py backend/tests/test_labels_router.py backend/app/main.py
git commit -m "feat(labels): add labels service + /api/labels CRUD"
```

---

### Task 5: Update Task model — drop project_id, add labels relationship

**Files:**
- Modify: `backend/app/tasks/models.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_labels_models.py`:

```python
from app.tasks.models import Task


def test_task_has_labels_relationship():
    assert "labels" in Task.__mapper__.relationships.keys()


def test_task_has_no_project_id_column():
    assert "project_id" not in Task.__table__.c
```

- [ ] **Step 2: Run, watch it fail**

```bash
cd backend && uv run pytest tests/test_labels_models.py -v
```

- [ ] **Step 3: Update Task model**

In `backend/app/tasks/models.py`:

Remove the `project_id` Mapped column (lines 48–54) and the `ForeignKey` import if no longer used elsewhere in this file. Add a labels relationship:

```python
from sqlalchemy.orm import relationship  # add to existing import block
from app.labels.models import Label, TaskLabel  # at module bottom to dodge circular


class Task(Base):
    ...  # keep existing columns except project_id

    labels: Mapped[list[Label]] = relationship(
        secondary="task_labels",
        order_by="Label.name",
        lazy="selectin",
    )
```

Place the relationship below `interval_count` and above the wake-loop counters. Keep all other columns + constraints unchanged.

- [ ] **Step 4: Tests pass**

```bash
cd backend && uv run pytest tests/test_labels_models.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/models.py backend/tests/test_labels_models.py
git commit -m "refactor(tasks): drop project_id, add labels many-to-many"
```

---

### Task 6: Update Task schemas + service for labels

**Files:**
- Modify: `backend/app/tasks/schemas.py`
- Modify: `backend/app/tasks/service.py`
- Modify: `backend/app/tasks/router.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_tasks_label_filter.py`:

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _label(slug: str) -> int:
    return client.post("/api/labels", json={"slug": slug, "name": slug}).json()["id"]


def test_create_task_with_labels_returns_them():
    _label("alpha")
    _label("beta")
    resp = client.post("/api/tasks", json={"title": "x", "labels": ["alpha", "beta"]})
    assert resp.status_code == 201
    assert set(resp.json()["labels"]) == {"alpha", "beta"}


def test_list_tasks_filtered_by_single_label():
    _label("home")
    _label("work")
    a = client.post("/api/tasks", json={"title": "a", "labels": ["home"]}).json()
    client.post("/api/tasks", json={"title": "b", "labels": ["work"]})
    resp = client.get("/api/tasks?label=home")
    titles = [t["title"] for t in resp.json()["tasks"]]
    assert "a" in titles and "b" not in titles


def test_list_tasks_filtered_by_multiple_labels_uses_or():
    _label("red")
    _label("blue")
    _label("green")
    client.post("/api/tasks", json={"title": "r", "labels": ["red"]})
    client.post("/api/tasks", json={"title": "b", "labels": ["blue"]})
    client.post("/api/tasks", json={"title": "g", "labels": ["green"]})
    resp = client.get("/api/tasks?label=red&label=blue")
    titles = sorted(t["title"] for t in resp.json()["tasks"])
    assert titles == ["b", "r"]


def test_patch_task_replaces_labels():
    _label("one")
    _label("two")
    created = client.post("/api/tasks", json={"title": "x", "labels": ["one"]}).json()
    resp = client.patch(f"/api/tasks/{created['id']}", json={"labels": ["two"]})
    assert resp.json()["labels"] == ["two"]
```

- [ ] **Step 2: Run them, watch them fail**

```bash
cd backend && uv run pytest tests/test_tasks_label_filter.py -v
```

- [ ] **Step 3: Update task schemas**

In `backend/app/tasks/schemas.py`:

- Remove `project_id` field from `TaskCreate` and `TaskUpdate` and `TaskRead`.
- Add `labels: list[str] = []` to `TaskCreate` and `TaskRead`.
- Add `labels: list[str] | None = None` to `TaskUpdate` (None = don't touch; empty list = clear).
- Update `task_to_read` to populate `labels` from `task.labels` (`[l.slug for l in task.labels]`).

Replace `TaskCreate` definition:

```python
class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    assignee: Assignee = "user"
    labels: list[str] = Field(default_factory=list)
    do_at: datetime | None = None
    due_at: datetime | None = None
    interval_unit: IntervalUnit | None = None
    interval_count: int | None = None
```

Replace `TaskUpdate`:

```python
class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    is_done: bool | None = None
    assignee: Assignee | None = None
    labels: list[str] | None = None
    do_at: datetime | None = None
    due_at: datetime | None = None
    interval_unit: IntervalUnit | None = None
    interval_count: int | None = None
```

Replace `TaskRead`:

```python
class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    assignee: Assignee
    is_done: bool
    state: str
    kind: str
    labels: list[str]
    chat_session_id: int | None
    do_at: datetime | None
    due_at: datetime | None
    interval_unit: IntervalUnit | None
    interval_count: int | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    source_chat_session_id: int | None = None
    source_chat_title: str | None = None
```

Update `task_to_read`:

```python
def task_to_read(task: Task) -> TaskRead:
    return TaskRead.model_validate(
        {
            **{c.name: getattr(task, c.name) for c in task.__table__.columns},
            "state": _state_of(task),
            "kind": _kind_of(task),
            "labels": [label.slug for label in task.labels],
        }
    )
```

- [ ] **Step 4: Update service**

In `backend/app/tasks/service.py`:

- Replace the `project_id` parameter on `list_tasks` with `labels: list[str] | None = None`.
- Drop the `include_archived_projects` parameter entirely.
- When filtering: if `labels` is given and non-empty, `WHERE EXISTS (SELECT 1 FROM task_labels JOIN labels ...)` matching any of the slugs (OR semantics).
- On `create_task`: resolve each slug to a `Label.id` (404-style if any missing — raise `ValueError`), insert into `task_labels`.
- On `update_task`: if `body.labels is not None`, delete current `task_labels` rows for the task and re-insert.
- Remove all `Project` references; remove the inbox fallback logic.

Concrete `list_tasks` body:

```python
def list_tasks(
    session: Session,
    *,
    labels: list[str] | None = None,
) -> list[Task]:
    stmt = select(Task)
    if labels:
        stmt = stmt.where(
            Task.id.in_(
                select(TaskLabel.task_id)
                .join(Label, Label.id == TaskLabel.label_id)
                .where(Label.slug.in_(labels))
            )
        )
    stmt = stmt.order_by(Task.created_at.desc())
    return list(session.scalars(stmt))
```

`create_task` body (relevant lines):

```python
def create_task(session: Session, body: TaskCreate) -> Task:
    label_objs = _resolve_labels(session, body.labels)
    task = Task(
        title=body.title,
        description=body.description,
        assignee=body.assignee,
        do_at=body.do_at,
        due_at=body.due_at,
        interval_unit=body.interval_unit,
        interval_count=body.interval_count,
    )
    task.labels = label_objs
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def _resolve_labels(session: Session, slugs: list[str]) -> list[Label]:
    if not slugs:
        return []
    found = list(session.scalars(select(Label).where(Label.slug.in_(slugs))))
    missing = set(slugs) - {label.slug for label in found}
    if missing:
        raise ValueError(f"unknown labels: {sorted(missing)}")
    return found
```

`update_task` should call `_resolve_labels` and reassign `task.labels` when `body.labels is not None`.

- [ ] **Step 5: Update tasks router**

In `backend/app/tasks/router.py`:

Change `list_tasks` signature:

```python
@router.get("/tasks")
def list_tasks(label: list[str] | None = Query(default=None)) -> dict[str, list[TaskRead]]:
    with SessionLocal() as session:
        tasks = service.list_tasks(session, labels=label)
        return {"tasks": [task_to_read(t) for t in tasks]}
```

Add `from fastapi import Query` to imports.

- [ ] **Step 6: Tests pass**

```bash
cd backend && uv run pytest tests/test_tasks_label_filter.py tests/test_labels_router.py -v
```

Expected: all green. Remove the `xfail` on `test_delete_label_clears_join_rows` from Task 4.

- [ ] **Step 7: Commit**

```bash
git add backend/app/tasks/schemas.py backend/app/tasks/service.py backend/app/tasks/router.py backend/tests/test_tasks_label_filter.py
git commit -m "feat(tasks): replace project filter with labels filter (OR semantics)"
```

---

### Task 7: Update agent tool to use labels

**Files:**
- Modify: `backend/app/agent/tools/tasks.py`

- [ ] **Step 1: Inspect current usage**

```bash
grep -n "project" backend/app/agent/tools/tasks.py
```

- [ ] **Step 2: Write the failing test**

If a test file already exists for this tool (look for `backend/tests/test_agent_tools_tasks.py`), add a case that calls the create-task tool with `labels=["foo"]`. Otherwise create a minimal smoke test that imports the tool spec and asserts its parameter schema includes `labels` and not `project_id`.

```python
# backend/tests/test_agent_tool_tasks_labels.py
from app.agent.tools.tasks import create_task_tool_spec  # adjust name to match actual export


def test_create_task_tool_lists_labels_not_project_id():
    schema = create_task_tool_spec()  # or equivalent accessor
    props = schema["parameters"]["properties"]
    assert "labels" in props
    assert "project_id" not in props
```

(If the tool module structures things differently, adapt to call the actual function/inspect the actual signature.)

- [ ] **Step 3: Edit the tool**

Replace every `project_id` reference with the labels equivalent. Tool parameter `labels: list[str]` (default `[]`) routed straight into the existing `service.create_task` / `service.update_task` calls.

Tool docstring stays neutral per the `feedback_tool_descriptions` rule — describe the tool's effect, do not instruct the model when to use it.

- [ ] **Step 4: Tests pass**

```bash
cd backend && uv run pytest tests/test_agent_tool_tasks_labels.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools/tasks.py backend/tests/test_agent_tool_tasks_labels.py
git commit -m "refactor(agent): task tool takes labels instead of project_id"
```

---

### Task 8: Delete the projects package

**Files:**
- Delete: `backend/app/projects/` (whole package).
- Modify: `backend/app/main.py` — remove the import + `include_router` line for projects.

- [ ] **Step 1: Confirm nothing imports `app.projects` anymore**

```bash
grep -rn "from app.projects\|app\.projects\." backend/app backend/tests
```

Expected: only matches inside `backend/app/projects/` itself plus the still-live registration in `main.py`.

- [ ] **Step 2: Remove the router registration**

In `backend/app/main.py`: delete the `from app.projects.router import router as projects_router` import and the matching `app.include_router(projects_router, prefix="/api")` line.

- [ ] **Step 3: Delete the package**

```bash
git rm -r backend/app/projects
```

- [ ] **Step 4: Smoke-test the API boots and tests pass**

```bash
cd backend && uv run pytest -q
```

Expected: all green. Fix any stale import.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/projects
git commit -m "chore(projects): delete projects package — replaced by labels"
```

---

### Task 9: Frontend labels API

**Files:**
- Create: `frontend/src/screens/Labels/labelsApi.ts`
- Create: `frontend/src/screens/Labels/labelsApi.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/screens/Labels/labelsApi.test.ts
import { describe, expect, it, vi } from "vitest";

import { createLabel, listLabels } from "./labelsApi";

describe("labelsApi", () => {
  it("listLabels hits /api/labels and returns the array", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ labels: [{ id: 1, slug: "a", name: "A" }] }), { status: 200 }),
    );
    const out = await listLabels();
    expect(fetchMock).toHaveBeenCalledWith("/api/labels", expect.anything());
    expect(out).toEqual([{ id: 1, slug: "a", name: "A" }]);
  });

  it("createLabel posts the body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: 9, slug: "x", name: "X" }), { status: 201 }),
    );
    const out = await createLabel({ slug: "x", name: "X" });
    expect(out.id).toBe(9);
  });
});
```

- [ ] **Step 2: Run, fail**

```bash
cd frontend && pnpm vitest run src/screens/Labels/labelsApi.test.ts
```

- [ ] **Step 3: Implement**

```ts
// frontend/src/screens/Labels/labelsApi.ts
export type Label = {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  color: string | null;
  icon: string | null;
};

export type LabelCreate = {
  slug: string;
  name: string;
  description?: string | null;
  color?: string | null;
  icon?: string | null;
};

export type LabelUpdate = Partial<Omit<LabelCreate, "slug">>;

export async function listLabels(): Promise<Label[]> {
  const res = await fetch("/api/labels", { credentials: "include" });
  if (!res.ok) throw new Error(`listLabels ${res.status}`);
  return (await res.json()).labels;
}

export async function createLabel(body: LabelCreate): Promise<Label> {
  const res = await fetch("/api/labels", {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`createLabel ${res.status}`);
  return res.json();
}

export async function updateLabel(id: number, body: LabelUpdate): Promise<Label> {
  const res = await fetch(`/api/labels/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`updateLabel ${res.status}`);
  return res.json();
}

export async function deleteLabel(id: number): Promise<void> {
  const res = await fetch(`/api/labels/${id}`, { method: "DELETE", credentials: "include" });
  if (!res.ok) throw new Error(`deleteLabel ${res.status}`);
}
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd frontend && pnpm vitest run src/screens/Labels/labelsApi.test.ts
git add frontend/src/screens/Labels/labelsApi.ts frontend/src/screens/Labels/labelsApi.test.ts
git commit -m "feat(labels): add frontend labelsApi"
```

---

### Task 10: Frontend ManageLabelsSheet

**Files:**
- Create: `frontend/src/screens/Labels/ManageLabelsSheet.tsx`
- Create: `frontend/src/screens/Labels/ManageLabelsSheet.test.tsx`

- [ ] **Step 1: Write a focused render test**

```tsx
// frontend/src/screens/Labels/ManageLabelsSheet.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ManageLabelsSheet } from "./ManageLabelsSheet";

vi.mock("./labelsApi", () => ({
  listLabels: vi.fn().mockResolvedValue([{ id: 1, slug: "home", name: "Home", description: null, color: null, icon: null }]),
  createLabel: vi.fn().mockResolvedValue({ id: 2, slug: "x", name: "X", description: null, color: null, icon: null }),
  updateLabel: vi.fn(),
  deleteLabel: vi.fn().mockResolvedValue(undefined),
}));

describe("ManageLabelsSheet", () => {
  it("lists existing labels", async () => {
    render(<ManageLabelsSheet open onClose={() => {}} />);
    expect(await screen.findByText("Home")).toBeInTheDocument();
  });

  it("calls createLabel when form submitted", async () => {
    const { createLabel } = await import("./labelsApi");
    render(<ManageLabelsSheet open onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/slug/i), { target: { value: "x" } });
    fireEvent.change(screen.getByPlaceholderText(/name/i), { target: { value: "X" } });
    fireEvent.click(screen.getByRole("button", { name: /add label/i }));
    await screen.findByText("X");
    expect(createLabel).toHaveBeenCalledWith({ slug: "x", name: "X" });
  });
});
```

- [ ] **Step 2: Run, fail**

```bash
cd frontend && pnpm vitest run src/screens/Labels/ManageLabelsSheet.test.tsx
```

- [ ] **Step 3: Implement the component**

Build a minimal sheet that mirrors the old ManageProjectsSheet shape: header, list of labels with delete buttons, footer with slug + name inputs and an "Add label" button. Skip icon/color UI for now — they exist on the model but the picker comes from Plan 3. Style with existing Tailwind tokens (`life-card`, `life-line`, etc.) — look at `ManageProjectsSheet.tsx` (about to be deleted) for the visual reference.

- [ ] **Step 4: Tests pass + commit**

```bash
cd frontend && pnpm vitest run src/screens/Labels/
git add frontend/src/screens/Labels
git commit -m "feat(labels): add ManageLabelsSheet"
```

---

### Task 11: Wire labels into TasksScreen + Task rows

**Files:**
- Modify: `frontend/src/screens/Tasks/tasksApi.ts`
- Modify: `frontend/src/screens/Tasks/TasksScreen.tsx`
- Modify: `frontend/src/screens/Tasks/TaskRow.tsx`
- Modify: `frontend/src/screens/Tasks/NewTaskSheet.tsx`
- Modify: `frontend/src/screens/Tasks/EditTaskSheet.tsx`
- Modify: `frontend/src/screens/Tasks/TaskDetailPage.tsx`
- Modify: `frontend/src/screens/Tasks/TasksScreen.test.tsx`
- Modify: `frontend/src/screens/Tasks/TaskRow.test.tsx`

- [ ] **Step 1: Update `tasksApi.ts`**

Find the `Task` type. Replace `project_id: number;` with `labels: string[];`. Replace any `ProjectFilter` plumbing with a `labels?: string[]` arg to `listTasks` that emits `?label=foo&label=bar`.

- [ ] **Step 2: Update TasksScreen**

Remove:
- `Project` import + `projects` state + `projectFilter` state + the project filter dropdown.
- `ManageProjectsSheet` import + `manageOpen` state + button.
- All `listProjects()` calls.

Keep the screen functional with a single flat list. (The richer label-filter / saved-views UI lands in Plan 2.) Render a temporary "Labels" button in the header that opens `ManageLabelsSheet`.

- [ ] **Step 3: Update TaskRow**

Drop the `projectLabel` prop and its chip. Render labels (small `#slug` pills) inline after the title — at most two slugs, then `+N`.

- [ ] **Step 4: Update New/Edit sheets**

Replace the project select control with a multi-select chip strip backed by `listLabels()`. Selected slugs go into `TaskCreate.labels` / `TaskUpdate.labels`.

- [ ] **Step 5: Update task detail page**

Replace the project line with a labels line that renders each slug as a chip linking to (eventually) the saved view filtered to that label — for now just static chips.

- [ ] **Step 6: Update tests**

- `TasksScreen.test.tsx`: drop project mocks, add `listLabels` mock; assert label chips render.
- `TaskRow.test.tsx`: replace `projectLabel` assertions with label chip assertions.

- [ ] **Step 7: Typecheck + run frontend tests**

```bash
cd frontend && pnpm typecheck && pnpm test
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/screens/Tasks
git commit -m "refactor(tasks): switch frontend to labels — drop project filter/UI"
```

---

### Task 12: Delete the frontend Projects package

**Files:**
- Delete: `frontend/src/screens/Projects/`
- Modify: any router file under `frontend/src/` that mounted a Projects route.

- [ ] **Step 1: Find references**

```bash
grep -rn "screens/Projects\|ManageProjectsSheet\|projectsApi" frontend/src/
```

- [ ] **Step 2: Remove route + import + delete files**

```bash
git rm -r frontend/src/screens/Projects
```

Update any router config or sidebar nav that referenced the projects screen — replace nav item with "Labels" pointing at ManageLabelsSheet, or drop entirely.

- [ ] **Step 3: Typecheck + tests pass**

```bash
cd frontend && pnpm typecheck && pnpm test
```

- [ ] **Step 4: Commit**

```bash
git add frontend
git commit -m "chore(projects): delete frontend Projects package"
```

---

### Task 13: Full CI parity — ruff, format, pytest, typecheck, vitest

- [ ] **Step 1: Backend lint**

```bash
cd backend && uv run ruff check . && uv run ruff format --check .
```

Fix any reported issues (apply `uv run ruff format .` for formatting nits).

- [ ] **Step 2: Backend tests**

```bash
cd backend && uv run pytest
```

- [ ] **Step 3: Frontend tests + typecheck + build**

```bash
cd frontend && pnpm typecheck && pnpm test && pnpm build
```

- [ ] **Step 4: Commit any formatter fixes; push**

```bash
git add -A
git commit -m "chore: ruff format pass"
git push -u origin task/$(git rev-parse --abbrev-ref HEAD | sed 's|.*/||')
```

---

## Test coverage map

| Behavior | Test file |
|---|---|
| Label model wiring | `backend/tests/test_labels_models.py` |
| Label schemas + slug validation | `backend/tests/test_labels_schemas.py` |
| Labels CRUD endpoints | `backend/tests/test_labels_router.py` |
| Migration backfills + drops projects | `backend/tests/test_migration_labels_backfill.py` |
| Task ↔ label filter (single, multi, replace) | `backend/tests/test_tasks_label_filter.py` |
| Agent task tool uses labels | `backend/tests/test_agent_tool_tasks_labels.py` |
| Frontend labelsApi fetches | `frontend/src/screens/Labels/labelsApi.test.ts` |
| ManageLabelsSheet renders + creates | `frontend/src/screens/Labels/ManageLabelsSheet.test.tsx` |
| TasksScreen renders without projects | `frontend/src/screens/Tasks/TasksScreen.test.tsx` (updated) |
| TaskRow shows label chips | `frontend/src/screens/Tasks/TaskRow.test.tsx` (updated) |

## Risk notes

- **Migration is one-way.** `downgrade()` raises. Take a backup of `data/otto.db` before running on a live VPS — see `deploy/backup.sh`.
- **Single-head Alembic.** If `main` advances before this lands, regenerate the migration with the new `down_revision` rather than merging multiple heads.
- **Agent runtime calls.** Any saved tool prompts or skills under `backend/defaults/skills/` that mention `project_id` need a sweep — grep before pushing.
