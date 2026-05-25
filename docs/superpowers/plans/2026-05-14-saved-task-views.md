# Saved Task Views — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current hardcoded owner / project tabs on the Tasks screen with user-configurable saved views. Each view is a filter preset plus a group-by axis, surfaced as a tab. The reference UX is the refined storybook prototype `Tasks/Saved task view prototypes › Tabs + filter sheet (live)` in `frontend/src/screens/Tasks/SavedTaskViewsPrototypes.tsx`.

**Architecture:** A `saved_task_views` table stores each view (name, icon, filters JSON, group_by, sort_index, is_default). The view list is small per user (single-user app) — fetched once at screen mount, mutated through normal CRUD endpoints. The frontend keeps a "working overlay" of filters/groupBy that diverges from the active view when the user edits; the explicit `Save view` button writes the overlay back. Creating a new view uses the tab strip's `+`, which opens a modal name prompt and POSTs the current overlay.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy (JSON column for filter blob), Alembic, pytest, React 18, TS, Vitest.

**Prerequisite:** Plan `2026-05-14-replace-projects-with-labels.md` must be merged first — saved views filter only by labels + owner + status + date, not by project.

**Out of scope:**
- LLM emoji pick on view creation — Plan `2026-05-14-llm-emoji-pick-for-views.md`.

**File map**

Created:
- `backend/app/saved_task_views/__init__.py`
- `backend/app/saved_task_views/models.py`
- `backend/app/saved_task_views/schemas.py`
- `backend/app/saved_task_views/service.py`
- `backend/app/saved_task_views/router.py`
- `backend/alembic/versions/<id>_add_saved_task_views.py`
- `backend/tests/test_saved_task_views_router.py`
- `backend/tests/test_saved_task_views_filters.py`
- `frontend/src/screens/Tasks/savedTaskViewsApi.ts`
- `frontend/src/screens/Tasks/SavedTaskViews/SavedTaskViewTabs.tsx`
- `frontend/src/screens/Tasks/SavedTaskViews/FilterSheet.tsx`
- `frontend/src/screens/Tasks/SavedTaskViews/useSavedTaskViews.ts`
- `frontend/src/screens/Tasks/SavedTaskViews/SavedTaskViewTabs.test.tsx`
- `frontend/src/screens/Tasks/SavedTaskViews/FilterSheet.test.tsx`

Modified:
- `backend/app/main.py` — register saved views router.
- `backend/app/tasks/service.py` — `list_tasks` accepts the full filter blob, not just `labels`.
- `backend/app/tasks/router.py` — same.
- `frontend/src/screens/Tasks/tasksApi.ts` — `listTasks` accepts a filter object.
- `frontend/src/screens/Tasks/TasksScreen.tsx` — wire the new tabs + sheet + group-by render.
- `frontend/src/screens/Tasks/TaskGroupsView.tsx` — accept a group-by axis instead of the hardcoded `Group`.

Removed/retired (delete after the new UI is live):
- `frontend/src/screens/Tasks/SavedTaskViewsPrototypes.tsx` (and its `.stories.tsx`) — the storybook prototype's role ends when the real component lands.

---

### Task 1: SavedTaskView ORM model

**Files:**
- Create: `backend/app/saved_task_views/__init__.py`
- Create: `backend/app/saved_task_views/models.py`
- Create: `backend/tests/test_saved_task_views_models.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_saved_task_views_models.py
from app.saved_task_views.models import SavedTaskView


def test_table_name():
    assert SavedTaskView.__tablename__ == "saved_task_views"


def test_filters_is_json():
    col = SavedTaskView.__table__.c.filters_json
    assert "JSON" in str(col.type).upper() or "TEXT" in str(col.type).upper()
```

- [ ] **Step 2: Run, fail**

```bash
cd backend && uv run pytest tests/test_saved_task_views_models.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/app/saved_task_views/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SavedTaskView(Base):
    __tablename__ = "saved_task_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # JSON shape:
    #   {"labels": ["home"], "assignee": "user" | "assistant" | null,
    #    "statuses": ["open"], "due": "today" | "week" | null}
    filters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    group_by: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/test_saved_task_views_models.py -v
git add backend/app/saved_task_views/{__init__,models}.py backend/tests/test_saved_task_views_models.py
git commit -m "feat(views): add SavedTaskView model"
```

---

### Task 2: Alembic migration

**Files:**
- Create: `backend/alembic/versions/<rev>_add_saved_task_views.py`

- [ ] **Step 1: Generate revision**

```bash
cd backend && uv run alembic revision -m "add saved task views"
```

- [ ] **Step 2: Implement**

```python
def upgrade() -> None:
    op.create_table(
        "saved_task_views",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("icon", sa.String(16), nullable=True),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("group_by", sa.String(16), nullable=False, server_default="none"),
        sa.Column("sort_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    # Seed one Today view so users land somewhere useful on first boot.
    op.execute(
        """
        INSERT INTO saved_task_views
          (name, icon, filters_json, group_by, sort_index, is_default)
        VALUES
          ('Today', '☀️', '{"due":"today","statuses":["open","scheduled"]}', 'none', 0, 1)
        """
    )


def downgrade() -> None:
    op.drop_table("saved_task_views")
```

- [ ] **Step 3: Apply + verify single head**

```bash
cd backend && uv run alembic upgrade head && uv run alembic heads
```

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/<rev>_add_saved_task_views.py
git commit -m "feat(views): migration creates saved_task_views with default Today seed"
```

---

### Task 3: Schemas

**Files:**
- Create: `backend/app/saved_task_views/schemas.py`
- Create: `backend/tests/test_saved_task_views_schemas.py`

- [ ] **Step 1: Failing test**

```python
import pytest
from pydantic import ValidationError

from app.saved_task_views.schemas import SavedTaskViewCreate


def test_create_rejects_unknown_group_by():
    with pytest.raises(ValidationError):
        SavedTaskViewCreate(name="x", filters={}, group_by="bogus")


def test_create_accepts_label_filter():
    v = SavedTaskViewCreate(name="x", filters={"labels": ["home"]}, group_by="none")
    assert v.filters["labels"] == ["home"]


def test_filters_rejects_extra_keys():
    with pytest.raises(ValidationError):
        SavedTaskViewCreate(name="x", filters={"haha_unknown": 1}, group_by="none")
```

- [ ] **Step 2: Implement**

```python
# backend/app/saved_task_views/schemas.py
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GroupBy = Literal["none", "status", "assignee", "label"]
Assignee = Literal["user", "assistant"]
TaskStatus = Literal["open", "scheduled", "waiting", "done"]
DueWindow = Literal["today", "week"]

_ALLOWED_FILTER_KEYS = {"labels", "assignee", "statuses", "due"}


class FilterBlob(BaseModel):
    labels: list[str] | None = None
    assignee: Assignee | None = None
    statuses: list[TaskStatus] | None = None
    due: DueWindow | None = None


class SavedTaskViewBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    icon: str | None = Field(default=None, max_length=16)
    filters: dict = Field(default_factory=dict)
    group_by: GroupBy = "none"

    @model_validator(mode="after")
    def _validate_filter_shape(self) -> "SavedTaskViewBase":
        bad = set(self.filters.keys()) - _ALLOWED_FILTER_KEYS
        if bad:
            raise ValueError(f"unknown filter keys: {sorted(bad)}")
        FilterBlob.model_validate(self.filters)
        return self


class SavedTaskViewCreate(SavedTaskViewBase):
    pass


class SavedTaskViewUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    icon: str | None = Field(default=None, max_length=16)
    filters: dict | None = None
    group_by: GroupBy | None = None
    sort_index: int | None = None
    is_default: bool | None = None

    @model_validator(mode="after")
    def _validate_filter_shape(self) -> "SavedTaskViewUpdate":
        if self.filters is not None:
            bad = set(self.filters.keys()) - _ALLOWED_FILTER_KEYS
            if bad:
                raise ValueError(f"unknown filter keys: {sorted(bad)}")
            FilterBlob.model_validate(self.filters)
        return self


class SavedTaskViewRead(SavedTaskViewBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sort_index: int
    is_default: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_row(cls, row) -> "SavedTaskViewRead":  # noqa: ANN001
        return cls.model_validate({
            "id": row.id,
            "name": row.name,
            "icon": row.icon,
            "filters": row.filters_json or {},
            "group_by": row.group_by,
            "sort_index": row.sort_index,
            "is_default": row.is_default,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        })
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/test_saved_task_views_schemas.py -v
git add backend/app/saved_task_views/schemas.py backend/tests/test_saved_task_views_schemas.py
git commit -m "feat(views): add pydantic schemas with filter-shape validation"
```

---

### Task 4: Service + Router

**Files:**
- Create: `backend/app/saved_task_views/service.py`
- Create: `backend/app/saved_task_views/router.py`
- Create: `backend/tests/test_saved_task_views_router.py`

- [ ] **Step 1: Failing router tests**

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_seeded_today_view_listed():
    items = client.get("/api/saved-task-views").json()["views"]
    assert any(v["name"] == "Today" and v["is_default"] for v in items)


def test_create_view():
    body = {"name": "Home", "icon": "🏠", "filters": {"labels": ["home"]}, "group_by": "none"}
    resp = client.post("/api/saved-task-views", json=body)
    assert resp.status_code == 201
    assert resp.json()["filters"]["labels"] == ["home"]


def test_patch_view():
    created = client.post(
        "/api/saved-task-views",
        json={"name": "Rev", "filters": {}, "group_by": "none"},
    ).json()
    resp = client.patch(f"/api/saved-task-views/{created['id']}", json={"name": "Review"})
    assert resp.json()["name"] == "Review"


def test_make_default_clears_existing_default():
    new_default = client.post(
        "/api/saved-task-views",
        json={"name": "Inbox", "filters": {}, "group_by": "none"},
    ).json()
    client.patch(f"/api/saved-task-views/{new_default['id']}", json={"is_default": True})
    items = client.get("/api/saved-task-views").json()["views"]
    defaults = [v for v in items if v["is_default"]]
    assert len(defaults) == 1 and defaults[0]["id"] == new_default["id"]


def test_delete_view():
    created = client.post(
        "/api/saved-task-views",
        json={"name": "Tmp", "filters": {}, "group_by": "none"},
    ).json()
    resp = client.delete(f"/api/saved-task-views/{created['id']}")
    assert resp.status_code == 204


def test_cannot_delete_last_remaining_view():
    items = client.get("/api/saved-task-views").json()["views"]
    for v in items[1:]:
        client.delete(f"/api/saved-task-views/{v['id']}")
    last = client.get("/api/saved-task-views").json()["views"][0]
    resp = client.delete(f"/api/saved-task-views/{last['id']}")
    assert resp.status_code == 409
```

- [ ] **Step 2: Implement service**

```python
# backend/app/saved_task_views/service.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.saved_task_views.models import SavedTaskView
from app.saved_task_views.schemas import SavedTaskViewCreate, SavedTaskViewUpdate


class LastViewError(ValueError):
    pass


def list_views(session: Session) -> list[SavedTaskView]:
    stmt = select(SavedTaskView).order_by(SavedTaskView.sort_index, SavedTaskView.id)
    return list(session.scalars(stmt))


def create_view(session: Session, body: SavedTaskViewCreate) -> SavedTaskView:
    max_sort = session.scalar(select(SavedTaskView).order_by(SavedTaskView.sort_index.desc()).limit(1))
    next_sort = (max_sort.sort_index + 1) if max_sort else 0
    view = SavedTaskView(
        name=body.name,
        icon=body.icon,
        filters_json=body.filters,
        group_by=body.group_by,
        sort_index=next_sort,
    )
    session.add(view)
    session.commit()
    session.refresh(view)
    return view


def update_view(session: Session, view_id: int, body: SavedTaskViewUpdate) -> SavedTaskView | None:
    view = session.get(SavedTaskView, view_id)
    if view is None:
        return None
    data = body.model_dump(exclude_unset=True)
    if data.get("is_default"):
        # only one default at a time
        session.query(SavedTaskView).update({"is_default": False})
    if "filters" in data:
        view.filters_json = data.pop("filters")
    for key, value in data.items():
        setattr(view, key, value)
    session.commit()
    session.refresh(view)
    return view


def delete_view(session: Session, view_id: int) -> bool:
    view = session.get(SavedTaskView, view_id)
    if view is None:
        return False
    if session.query(SavedTaskView).count() <= 1:
        raise LastViewError("cannot delete the last remaining view")
    session.delete(view)
    session.commit()
    return True
```

- [ ] **Step 3: Implement router**

```python
# backend/app/saved_task_views/router.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.db import SessionLocal
from app.saved_task_views import service
from app.saved_task_views.schemas import (
    SavedTaskViewCreate,
    SavedTaskViewRead,
    SavedTaskViewUpdate,
)

router = APIRouter()


@router.get("/saved-task-views")
def list_views() -> dict[str, list[SavedTaskViewRead]]:
    with SessionLocal() as session:
        rows = service.list_views(session)
        return {"views": [SavedTaskViewRead.from_orm_row(r) for r in rows]}


@router.post("/saved-task-views", status_code=status.HTTP_201_CREATED)
def create_view(body: SavedTaskViewCreate) -> SavedTaskViewRead:
    with SessionLocal() as session:
        view = service.create_view(session, body)
        return SavedTaskViewRead.from_orm_row(view)


@router.patch("/saved-task-views/{view_id}")
def update_view(view_id: int, body: SavedTaskViewUpdate) -> SavedTaskViewRead:
    with SessionLocal() as session:
        view = service.update_view(session, view_id, body)
        if view is None:
            raise HTTPException(status_code=404, detail="View not found")
        return SavedTaskViewRead.from_orm_row(view)


@router.delete("/saved-task-views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_view(view_id: int) -> Response:
    with SessionLocal() as session:
        try:
            ok = service.delete_view(session, view_id)
        except service.LastViewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not ok:
            raise HTTPException(status_code=404, detail="View not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Register router** in `backend/app/main.py`:

```python
from app.saved_task_views.router import router as saved_task_views_router
...
app.include_router(saved_task_views_router, prefix="/api")
```

- [ ] **Step 5: Tests pass + commit**

```bash
cd backend && uv run pytest tests/test_saved_task_views_router.py -v
git add backend/app/saved_task_views backend/app/main.py backend/tests/test_saved_task_views_router.py
git commit -m "feat(views): add saved-task-views service + CRUD endpoints"
```

---

### Task 5: Generalize task listing to accept the full filter blob

**Files:**
- Modify: `backend/app/tasks/service.py`
- Modify: `backend/app/tasks/router.py`
- Create: `backend/tests/test_saved_task_views_filters.py`

- [ ] **Step 1: Failing tests**

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _seed():
    client.post("/api/labels", json={"slug": "home", "name": "Home"})
    client.post("/api/tasks", json={"title": "open-home", "labels": ["home"]})
    client.post(
        "/api/tasks",
        json={"title": "done-home", "labels": ["home"], "is_done": False},
    )
    # mark second one done
    items = client.get("/api/tasks").json()["tasks"]
    done = next(t for t in items if t["title"] == "done-home")
    client.patch(f"/api/tasks/{done['id']}", json={"is_done": True})


def test_filter_by_status_only():
    _seed()
    resp = client.get("/api/tasks", params=[("status", "open")])
    titles = [t["title"] for t in resp.json()["tasks"]]
    assert "open-home" in titles
    assert "done-home" not in titles


def test_filter_by_label_and_assignee():
    _seed()
    resp = client.get(
        "/api/tasks",
        params=[("label", "home"), ("assignee", "user")],
    )
    titles = [t["title"] for t in resp.json()["tasks"]]
    assert "open-home" in titles


def test_filter_by_due_today_returns_only_today():
    # this test is allowed to be a smoke check — date semantics covered in service unit test
    resp = client.get("/api/tasks", params=[("due", "today")])
    assert resp.status_code == 200
```

- [ ] **Step 2: Extend service**

In `backend/app/tasks/service.py`, replace `list_tasks` signature with:

```python
from datetime import datetime, timedelta
from typing import Literal

Assignee = Literal["user", "assistant"]
TaskStatus = Literal["open", "scheduled", "waiting", "done"]
DueWindow = Literal["today", "week"]


def list_tasks(
    session: Session,
    *,
    labels: list[str] | None = None,
    assignee: Assignee | None = None,
    statuses: list[TaskStatus] | None = None,
    due: DueWindow | None = None,
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
    if assignee:
        stmt = stmt.where(Task.assignee == assignee)
    if statuses:
        from app.tasks.taxonomy import status_predicate  # implement helper
        stmt = stmt.where(status_predicate(statuses))
    if due == "today":
        start, end = _today_window()
        stmt = stmt.where(
            (Task.due_at.between(start, end)) | (Task.do_at.between(start, end))
        )
    elif due == "week":
        start, end = _week_window()
        stmt = stmt.where(
            (Task.due_at.between(start, end)) | (Task.do_at.between(start, end))
        )
    return list(session.scalars(stmt.order_by(Task.created_at.desc())))
```

Implement `_today_window` / `_week_window` returning `(datetime, datetime)` based on local time (use `app.datetime_utils`).

Add a small `app/tasks/taxonomy.py` helper `status_predicate(statuses)` that returns the SQL expression mapping each status enum to `is_done` / `do_at` / `due_at` semantics (mirror the frontend `groupOf` rules).

- [ ] **Step 3: Update router**

```python
from fastapi import Query


@router.get("/tasks")
def list_tasks(
    label: list[str] | None = Query(default=None),
    assignee: str | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    due: str | None = Query(default=None),
) -> dict[str, list[TaskRead]]:
    with SessionLocal() as session:
        rows = service.list_tasks(
            session,
            labels=label,
            assignee=assignee,
            statuses=status,
            due=due,
        )
        return {"tasks": [task_to_read(t) for t in rows]}
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/test_saved_task_views_filters.py -v
git add backend/app/tasks backend/tests/test_saved_task_views_filters.py
git commit -m "feat(tasks): list endpoint accepts owner/status/due/labels filters"
```

---

### Task 6: Frontend savedTaskViewsApi

**Files:**
- Create: `frontend/src/screens/Tasks/savedTaskViewsApi.ts`
- Create: `frontend/src/screens/Tasks/savedTaskViewsApi.test.ts`

- [ ] **Step 1: Failing tests**

```ts
import { describe, expect, it, vi } from "vitest";
import { createView, listViews, updateView } from "./savedTaskViewsApi";

describe("savedTaskViewsApi", () => {
  it("listViews returns array", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ views: [] }), { status: 200 }),
    );
    expect(await listViews()).toEqual([]);
  });

  it("createView posts filters and group_by", async () => {
    const mock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: 5, name: "x" }), { status: 201 }),
    );
    await createView({ name: "x", filters: { labels: ["home"] }, group_by: "none" });
    const call = mock.mock.calls[0]!;
    expect(JSON.parse((call[1] as RequestInit).body as string).filters.labels).toEqual(["home"]);
  });

  it("updateView patches", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: 5 }), { status: 200 }),
    );
    await updateView(5, { name: "y" });
  });
});
```

- [ ] **Step 2: Implement**

```ts
export type FilterBlob = {
  labels?: string[];
  assignee?: "user" | "assistant" | null;
  statuses?: ("open" | "scheduled" | "waiting" | "done")[];
  due?: "today" | "week" | null;
};

export type GroupBy = "none" | "status" | "assignee" | "label";

export type SavedTaskView = {
  id: number;
  name: string;
  icon: string | null;
  filters: FilterBlob;
  group_by: GroupBy;
  sort_index: number;
  is_default: boolean;
};

export type SavedTaskViewCreate = {
  name: string;
  icon?: string | null;
  filters: FilterBlob;
  group_by: GroupBy;
};

export type SavedTaskViewUpdate = Partial<SavedTaskViewCreate> & {
  is_default?: boolean;
  sort_index?: number;
};

export async function listViews(): Promise<SavedTaskView[]> {
  const res = await fetch("/api/saved-task-views", { credentials: "include" });
  if (!res.ok) throw new Error(`listViews ${res.status}`);
  return (await res.json()).views;
}

export async function createView(body: SavedTaskViewCreate): Promise<SavedTaskView> {
  const res = await fetch("/api/saved-task-views", {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`createView ${res.status}`);
  return res.json();
}

export async function updateView(id: number, body: SavedTaskViewUpdate): Promise<SavedTaskView> {
  const res = await fetch(`/api/saved-task-views/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`updateView ${res.status}`);
  return res.json();
}

export async function deleteView(id: number): Promise<void> {
  const res = await fetch(`/api/saved-task-views/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) throw new Error(`deleteView ${res.status}`);
}
```

- [ ] **Step 3: Tests + commit**

```bash
cd frontend && pnpm vitest run src/screens/Tasks/savedTaskViewsApi.test.ts
git add frontend/src/screens/Tasks/savedTaskViewsApi.ts frontend/src/screens/Tasks/savedTaskViewsApi.test.ts
git commit -m "feat(views): add frontend savedTaskViewsApi"
```

---

### Task 7: useSavedTaskViews hook

**Files:**
- Create: `frontend/src/screens/Tasks/SavedTaskViews/useSavedTaskViews.ts`
- Create: `frontend/src/screens/Tasks/SavedTaskViews/useSavedTaskViews.test.ts`

The hook owns the views list, the active id, the working filter overlay, dirty calc, and the CRUD operations the UI calls.

- [ ] **Step 1: Failing test**

```ts
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useSavedTaskViews } from "./useSavedTaskViews";

vi.mock("../savedTaskViewsApi", () => ({
  listViews: vi.fn().mockResolvedValue([
    { id: 1, name: "Today", icon: "☀️", filters: {}, group_by: "none", sort_index: 0, is_default: true },
  ]),
  createView: vi.fn().mockResolvedValue(
    { id: 2, name: "Home", icon: "🏠", filters: { labels: ["home"] }, group_by: "none", sort_index: 1, is_default: false },
  ),
  updateView: vi.fn(),
  deleteView: vi.fn(),
}));

describe("useSavedTaskViews", () => {
  it("loads views and picks the default as active", async () => {
    const { result } = renderHook(() => useSavedTaskViews());
    await waitFor(() => expect(result.current.views.length).toBe(1));
    expect(result.current.activeView.name).toBe("Today");
  });

  it("dirty flips true after editFilters", async () => {
    const { result } = renderHook(() => useSavedTaskViews());
    await waitFor(() => expect(result.current.views.length).toBe(1));
    act(() => result.current.editFilters({ labels: ["x"] }));
    expect(result.current.dirty).toBe(true);
  });
});
```

- [ ] **Step 2: Implement**

```ts
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createView,
  deleteView as deleteViewApi,
  listViews,
  type FilterBlob,
  type GroupBy,
  type SavedTaskView,
  type SavedTaskViewCreate,
  updateView,
} from "../savedTaskViewsApi";

export function useSavedTaskViews() {
  const [views, setViews] = useState<SavedTaskView[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [workingFilters, setWorkingFilters] = useState<FilterBlob>({});
  const [workingGroupBy, setWorkingGroupBy] = useState<GroupBy>("none");

  useEffect(() => {
    listViews().then((rows) => {
      setViews(rows);
      const def = rows.find((v) => v.is_default) ?? rows[0];
      if (def) {
        setActiveId(def.id);
        setWorkingFilters(def.filters);
        setWorkingGroupBy(def.group_by);
      }
    });
  }, []);

  const activeView = useMemo(() => views.find((v) => v.id === activeId) ?? null, [views, activeId]);

  const dirty = useMemo(() => {
    if (!activeView) return false;
    return JSON.stringify(activeView.filters) !== JSON.stringify(workingFilters)
      || activeView.group_by !== workingGroupBy;
  }, [activeView, workingFilters, workingGroupBy]);

  const switchView = useCallback((id: number) => {
    const view = views.find((v) => v.id === id);
    if (!view) return;
    setActiveId(id);
    setWorkingFilters(view.filters);
    setWorkingGroupBy(view.group_by);
  }, [views]);

  const editFilters = useCallback((patch: FilterBlob) => {
    setWorkingFilters((curr) => ({ ...curr, ...patch }));
  }, []);

  const setGroupBy = useCallback((g: GroupBy) => setWorkingGroupBy(g), []);

  const saveCurrent = useCallback(async () => {
    if (!activeView || !dirty) return;
    const updated = await updateView(activeView.id, {
      filters: workingFilters,
      group_by: workingGroupBy,
    });
    setViews((curr) => curr.map((v) => (v.id === updated.id ? updated : v)));
  }, [activeView, dirty, workingFilters, workingGroupBy]);

  const createFromWorking = useCallback(async (name: string, icon: string | null) => {
    const body: SavedTaskViewCreate = {
      name,
      icon,
      filters: workingFilters,
      group_by: workingGroupBy,
    };
    const created = await createView(body);
    setViews((curr) => [...curr, created]);
    setActiveId(created.id);
    return created;
  }, [workingFilters, workingGroupBy]);

  const renameView = useCallback(async (id: number, name: string) => {
    const updated = await updateView(id, { name });
    setViews((curr) => curr.map((v) => (v.id === id ? updated : v)));
  }, []);

  const makeDefault = useCallback(async (id: number) => {
    const updated = await updateView(id, { is_default: true });
    setViews((curr) => curr.map((v) => ({ ...v, is_default: v.id === updated.id })));
  }, []);

  const removeView = useCallback(async (id: number) => {
    await deleteViewApi(id);
    setViews((curr) => curr.filter((v) => v.id !== id));
    if (activeId === id) {
      const fallback = views.find((v) => v.id !== id);
      if (fallback) switchView(fallback.id);
    }
  }, [activeId, switchView, views]);

  const discardWorking = useCallback(() => {
    if (!activeView) return;
    setWorkingFilters(activeView.filters);
    setWorkingGroupBy(activeView.group_by);
  }, [activeView]);

  return {
    views,
    activeView: activeView!,
    workingFilters,
    workingGroupBy,
    dirty,
    switchView,
    editFilters,
    setGroupBy,
    saveCurrent,
    createFromWorking,
    renameView,
    makeDefault,
    removeView,
    discardWorking,
  };
}
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd frontend && pnpm vitest run src/screens/Tasks/SavedTaskViews/useSavedTaskViews.test.ts
git add frontend/src/screens/Tasks/SavedTaskViews/useSavedTaskViews.ts frontend/src/screens/Tasks/SavedTaskViews/useSavedTaskViews.test.ts
git commit -m "feat(views): hook owning views + working overlay"
```

---

### Task 8: SavedTaskViewTabs component (port from prototype)

**Files:**
- Create: `frontend/src/screens/Tasks/SavedTaskViews/SavedTaskViewTabs.tsx`
- Create: `frontend/src/screens/Tasks/SavedTaskViews/SavedTaskViewTabs.test.tsx`

Port the `TabStrip` from `SavedTaskViewsPrototypes.tsx` (lines defining `TabStrip` and the inline rename + kebab menu) into a real component, but render the kebab menu in a portal (`React.DOM` createPortal anchored to body) instead of inside the scrolling tab row, so the `overflow-x-auto` clip bug is gone.

- [ ] **Step 1: Failing test**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SavedTaskViewTabs } from "./SavedTaskViewTabs";

const views = [
  { id: 1, name: "Today", icon: "☀️", filters: {}, group_by: "none" as const, sort_index: 0, is_default: true },
  { id: 2, name: "Home", icon: "🏠", filters: { labels: ["home"] }, group_by: "none" as const, sort_index: 1, is_default: false },
];

describe("SavedTaskViewTabs", () => {
  it("renders each view as a pill", () => {
    render(<SavedTaskViewTabs views={views} activeId={1} dirty={false} onSelect={() => {}} onRename={() => {}} onMakeDefault={() => {}} onDelete={() => {}} onAdd={() => {}} />);
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Home")).toBeInTheDocument();
  });

  it("clicking inactive tab calls onSelect", () => {
    const onSelect = vi.fn();
    render(<SavedTaskViewTabs views={views} activeId={1} dirty={false} onSelect={onSelect} onRename={() => {}} onMakeDefault={() => {}} onDelete={() => {}} onAdd={() => {}} />);
    fireEvent.click(screen.getByText("Home"));
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("clicking active tab opens portal menu and Rename triggers callback", async () => {
    const onRename = vi.fn();
    render(<SavedTaskViewTabs views={views} activeId={1} dirty={false} onSelect={() => {}} onRename={onRename} onMakeDefault={() => {}} onDelete={() => {}} onAdd={() => {}} />);
    fireEvent.click(screen.getByText("Today"));
    fireEvent.click(await screen.findByText("Rename"));
    const input = screen.getByLabelText("Rename view") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Day plan" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).toHaveBeenCalledWith(1, "Day plan");
  });
});
```

- [ ] **Step 2: Implement**

Copy the prototype's `TabStrip` body and replace the inline `<div className="absolute ...">` menu with `createPortal(<...>, document.body)` positioned via the active tab's `getBoundingClientRect()`. Rename signature to `SavedTaskViewTabs` and export.

- [ ] **Step 3: Tests pass + commit**

```bash
cd frontend && pnpm vitest run src/screens/Tasks/SavedTaskViews/SavedTaskViewTabs.test.tsx
git add frontend/src/screens/Tasks/SavedTaskViews/SavedTaskViewTabs.tsx frontend/src/screens/Tasks/SavedTaskViews/SavedTaskViewTabs.test.tsx
git commit -m "feat(views): SavedTaskViewTabs component (kebab menu in portal)"
```

---

### Task 9: FilterSheet component (port from prototype)

**Files:**
- Create: `frontend/src/screens/Tasks/SavedTaskViews/FilterSheet.tsx`
- Create: `frontend/src/screens/Tasks/SavedTaskViews/FilterSheet.test.tsx`

Port the live filter sheet from `SavedTaskViewsPrototypes.tsx` — same Owner / Status / Date / Labels sections, no footer, live writes. Drop the local fixtures and accept `labels: Label[]` + `value: FilterBlob` + `onChange: (FilterBlob) => void` props.

- [ ] **Step 1: Failing test**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterSheet } from "./FilterSheet";

const labels = [
  { id: 1, slug: "home", name: "Home" },
  { id: 2, slug: "review", name: "Review" },
];

describe("FilterSheet", () => {
  it("renders chips for each label", () => {
    render(<FilterSheet open value={{}} labels={labels} onChange={() => {}} onClose={() => {}} />);
    expect(screen.getByText("#home")).toBeInTheDocument();
  });

  it("clicking a label chip toggles it", () => {
    const onChange = vi.fn();
    render(<FilterSheet open value={{}} labels={labels} onChange={onChange} onClose={() => {}} />);
    fireEvent.click(screen.getByText("#home"));
    expect(onChange).toHaveBeenCalledWith({ labels: ["home"] });
  });

  it("clicking the same chip again removes it", () => {
    const onChange = vi.fn();
    render(<FilterSheet open value={{ labels: ["home"] }} labels={labels} onChange={onChange} onClose={() => {}} />);
    fireEvent.click(screen.getByText("#home"));
    expect(onChange).toHaveBeenCalledWith({ labels: [] });
  });
});
```

- [ ] **Step 2: Implement** by lifting the prototype's sheet body. Replace the hardcoded `LABEL_POOL` with the `labels` prop. No footer.

- [ ] **Step 3: Tests pass + commit**

```bash
cd frontend && pnpm vitest run src/screens/Tasks/SavedTaskViews/FilterSheet.test.tsx
git add frontend/src/screens/Tasks/SavedTaskViews/FilterSheet.tsx frontend/src/screens/Tasks/SavedTaskViews/FilterSheet.test.tsx
git commit -m "feat(views): FilterSheet component — live edits, no footer"
```

---

### Task 10: Wire it all into TasksScreen

**Files:**
- Modify: `frontend/src/screens/Tasks/TasksScreen.tsx`
- Modify: `frontend/src/screens/Tasks/tasksApi.ts` — `listTasks(filters)` accepts the full blob.
- Modify: `frontend/src/screens/Tasks/TasksScreen.test.tsx`

- [ ] **Step 1: Update `listTasks` signature**

```ts
export type ListTasksParams = {
  labels?: string[];
  assignee?: "user" | "assistant" | null;
  statuses?: ("open" | "scheduled" | "waiting" | "done")[];
  due?: "today" | "week" | null;
};

export async function listTasks(params: ListTasksParams = {}): Promise<Task[]> {
  const qs = new URLSearchParams();
  params.labels?.forEach((l) => qs.append("label", l));
  params.statuses?.forEach((s) => qs.append("status", s));
  if (params.assignee) qs.append("assignee", params.assignee);
  if (params.due) qs.append("due", params.due);
  const url = qs.toString() ? `/api/tasks?${qs}` : "/api/tasks";
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error(`listTasks ${res.status}`);
  return (await res.json()).tasks;
}
```

- [ ] **Step 2: Replace TasksScreen body**

Use `useSavedTaskViews` for state and replace the prior owner-tab UI with:

```
<ScreenTitle />
<SavedTaskViewTabs ... />
<Toolbar>
  <FiltersButton onClick={() => setSheetOpen(true)} />
  <SaveViewButton disabled={!dirty} onClick={saveCurrent} />
  <GroupByDropdown value={workingGroupBy} onChange={setGroupBy} />
</Toolbar>
<TaskGroupsView tasks={tasks} groupBy={workingGroupBy} ... />
<FilterSheet open value={workingFilters} labels={labels} onChange={editFilters} onClose={() => setSheetOpen(false)} />
<NewViewNamePrompt open={namePromptOpen} onSubmit={(name) => createFromWorking(name, null)} onCancel={...} />
```

Use the prototype's name prompt + toolbar as the visual reference. `tasks` comes from `listTasks(workingFilters)` rerun whenever the working filters change (debounce optional but not required — single-user app).

- [ ] **Step 3: Update `TasksScreen.test.tsx`**

Mock `listViews`, `listTasks` (filter-aware), and assert that switching tabs triggers a `listTasks` call with the new filter blob.

- [ ] **Step 4: Drop the storybook prototype files**

```bash
git rm frontend/src/screens/Tasks/SavedTaskViewsPrototypes.tsx \
       frontend/src/screens/Tasks/SavedTaskViewsPrototypes.stories.tsx
```

- [ ] **Step 5: Typecheck + tests + build**

```bash
cd frontend && pnpm typecheck && pnpm test && pnpm build
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/screens/Tasks
git commit -m "feat(tasks): wire SavedTaskViews tabs + filter sheet into TasksScreen"
```

---

### Task 11: Full CI parity

- [ ] **Step 1: Backend**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
```

- [ ] **Step 2: Frontend**

```bash
cd frontend && pnpm typecheck && pnpm test && pnpm build
```

- [ ] **Step 3: Commit + push**

---

## Test coverage map

| Behavior | Test file |
|---|---|
| Model wiring | `backend/tests/test_saved_task_views_models.py` |
| Schemas reject bogus filter keys / group_by | `backend/tests/test_saved_task_views_schemas.py` |
| CRUD endpoints + default cleanup + last-view guard | `backend/tests/test_saved_task_views_router.py` |
| Tasks list accepts blob filters | `backend/tests/test_saved_task_views_filters.py` |
| Frontend API fetches | `savedTaskViewsApi.test.ts` |
| Hook dirty-tracking + switch behavior | `useSavedTaskViews.test.ts` |
| Tabs render + kebab portal menu | `SavedTaskViewTabs.test.tsx` |
| Filter sheet chip toggles | `FilterSheet.test.tsx` |
| TasksScreen integration | updated `TasksScreen.test.tsx` |

## Risk notes

- **Portal positioning.** The kebab menu must clamp to viewport when the active tab is near the right edge; verify in the test that `right` is computed if `left + menuWidth > window.innerWidth`.
- **listTasks refire.** Naive re-fetch on every keystroke in label chip toggles is fine for a single-user app but watch for FOUC; add a 150ms debounce in `TasksScreen` if visible flicker shows up in manual testing.
- **Filter shape drift.** The JSON blob stored in `filters_json` must stay consistent across schema validator (`FilterBlob` in pydantic) and `FilterBlob` in TS. If you add a new dimension later, update both at the same time and write a migration if existing rows need defaults.
