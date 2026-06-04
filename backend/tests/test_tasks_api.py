"""End-to-end tests for the Tasks HTTP API."""

from __future__ import annotations

import asyncio
from datetime import datetime


def test_list_empty(client):
    r = client.get("/api/tasks")
    assert r.status_code == 200
    assert r.json() == {"tasks": []}


def test_create_regular_task(client):
    r = client.post("/api/tasks", json={"title": "Write tests"})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Write tests"
    assert body["description"] is None
    assert body["is_done"] is False
    assert body["assignee"] == "user"  # default via HTTP is 'user'
    # User-owned, not done → state 'yours'.
    assert body["state"] == "yours"
    assert body["do_at"] is None
    assert body["interval_unit"] is None
    assert body["interval_count"] is None
    # Each task auto-creates its own chat session.
    assert isinstance(body["chat_session_id"], int)


def test_create_scheduled_task(client):
    r = client.post(
        "/api/tasks",
        json={
            "title": "Check in",
            "assignee": "assistant",
            "do_at": "2099-04-27T14:30:00",
        },
    )
    assert r.status_code == 201
    # Future do_at on an assistant task → 'up_next'.
    assert r.json()["state"] == "up_next"


def test_create_recurring_task(client):
    r = client.post(
        "/api/tasks",
        json={
            "title": "Stretch",
            "assignee": "assistant",
            "interval_unit": "day",
            "interval_count": 2,
        },
    )
    assert r.status_code == 201
    body = r.json()
    # No do_at → first run is now → 'running'.
    assert body["state"] == "running"
    assert body["interval_unit"] == "day"
    assert body["interval_count"] == 2


def test_create_accepts_assignee_override(client):
    r = client.post(
        "/api/tasks",
        json={"title": "Nix-owned", "assignee": "assistant"},
    )
    assert r.status_code == 201
    assert r.json()["assignee"] == "assistant"


def test_create_rejects_invalid_assignee(client):
    r = client.post("/api/tasks", json={"title": "Bad", "assignee": "nobody"})
    assert r.status_code == 422


def test_create_rejects_invalid_interval_unit(client):
    r = client.post(
        "/api/tasks",
        json={"title": "Bad", "interval_unit": "minute", "interval_count": 5},
    )
    assert r.status_code == 422


def test_create_rejects_half_interval(client):
    r = client.post(
        "/api/tasks",
        json={"title": "Bad", "interval_unit": "day"},
    )
    assert r.status_code == 422

    r = client.post(
        "/api/tasks",
        json={"title": "Bad", "interval_count": 3},
    )
    assert r.status_code == 422


def test_create_rejects_zero_interval_count(client):
    r = client.post(
        "/api/tasks",
        json={"title": "Bad", "interval_unit": "day", "interval_count": 0},
    )
    assert r.status_code == 422


def test_create_rejects_empty_title(client):
    r = client.post("/api/tasks", json={"title": ""})
    assert r.status_code == 422


def test_list_sorts_open_before_done(client):
    ids = {}
    for name in ["a_done", "b_open", "c_open"]:
        r = client.post("/api/tasks", json={"title": name})
        ids[name] = r.json()["id"]
    u = client.patch(f"/api/tasks/{ids['a_done']}", json={"is_done": True})
    assert u.status_code == 200

    r = client.get("/api/tasks")
    statuses = [t["is_done"] for t in r.json()["tasks"]]
    # Open tasks first, done last.
    assert statuses == [False, False, True]


def test_open_sorted_by_last_activity(client):
    """`?done=false` orders open tasks by last activity (a chat message
    bumps a task above more-recently-created ones)."""
    from app.db import SessionLocal
    from tests._message_factory import make_message

    ids = {}
    chats = {}
    for name in ["a", "b", "c"]:
        r = client.post("/api/tasks", json={"title": name})
        ids[name] = r.json()["id"]
        chats[name] = r.json()["chat_session_id"]

    # Post a message into the *oldest* task's session — it should jump to
    # the front of the activity-ordered open feed. Stamp it explicitly in
    # the future so the assertion can't flake on same-second timestamps.
    with SessionLocal() as s:
        s.add(
            make_message(
                session_id=chats["a"],
                kind="response",
                parts_json={"parts": [{"part_kind": "text", "content": "ping"}]},
                created_at=datetime(2099, 1, 1, 0, 0, 0),
            )
        )
        s.commit()

    r = client.get("/api/tasks?done=false")
    assert r.status_code == 200
    order = [t["id"] for t in r.json()["tasks"]]
    assert order[0] == ids["a"]
    assert set(order) == {ids["a"], ids["b"], ids["c"]}


def test_list_done_param_splits_open_and_done(client):
    open_id = client.post("/api/tasks", json={"title": "open"}).json()["id"]
    done_id = client.post("/api/tasks", json={"title": "done"}).json()["id"]
    client.patch(f"/api/tasks/{done_id}", json={"is_done": True})

    open_only = client.get("/api/tasks?done=false").json()["tasks"]
    assert [t["id"] for t in open_only] == [open_id]

    done_only = client.get("/api/tasks?done=true").json()
    assert [t["id"] for t in done_only["tasks"]] == [done_id]
    assert done_only["next_cursor"] is None

    # No `done` → legacy slice, both present, open-before-done.
    legacy = client.get("/api/tasks").json()["tasks"]
    assert [t["is_done"] for t in legacy] == [False, True]


def test_legacy_status_param_still_filters(client):
    """`status` is back-compat: no 422, still narrows the legacy slice."""
    open_id = client.post("/api/tasks", json={"title": "open"}).json()["id"]
    done_id = client.post("/api/tasks", json={"title": "done"}).json()["id"]
    client.patch(f"/api/tasks/{done_id}", json={"is_done": True})

    r = client.get("/api/tasks?status=open")
    assert r.status_code == 200
    assert [t["id"] for t in r.json()["tasks"]] == [open_id]


def test_recurring_spawn_lands_open(client, monkeypatch):
    from app.chat import runner

    monkeypatch.setattr(runner, "schedule_wake", lambda sid: None)

    create = client.post(
        "/api/tasks",
        json={
            "title": "Daily digest",
            "assignee": "assistant",
            "do_at": "2099-04-27T09:00:00",
            "interval_unit": "day",
            "interval_count": 1,
        },
    )
    task_id = create.json()["id"]
    client.patch(f"/api/tasks/{task_id}", json={"is_done": True})

    open_titles = [t["title"] for t in client.get("/api/tasks?done=false").json()["tasks"]]
    assert "Daily digest" in open_titles  # the spawned next instance

    done_ids = [t["id"] for t in client.get("/api/tasks?done=true").json()["tasks"]]
    assert task_id in done_ids  # the completed predecessor


def test_done_pagination_walks_cursor_to_exhaustion(client):
    ids = []
    for i in range(5):
        tid = client.post("/api/tasks", json={"title": f"d{i}"}).json()["id"]
        client.patch(f"/api/tasks/{tid}", json={"is_done": True})
        ids.append(tid)

    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        url = "/api/tasks?done=true&limit=2"
        if cursor:
            url += f"&cursor={cursor}"
        body = client.get(url).json()
        page = [t["id"] for t in body["tasks"]]
        assert len(page) <= 2
        seen.extend(page)
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
        assert pages < 10  # guard against a non-terminating cursor

    assert sorted(seen) == sorted(ids)
    assert len(seen) == len(set(seen))  # no row served twice


def test_done_cursor_tamper_safe(client):
    r = client.get("/api/tasks?done=true&cursor=not-a-valid-cursor")
    assert r.status_code == 422


def test_patch_is_done_sets_completed_at(client):
    create = client.post("/api/tasks", json={"title": "Finish"})
    task_id = create.json()["id"]
    assert create.json()["completed_at"] is None

    r = client.patch(f"/api/tasks/{task_id}", json={"is_done": True})
    assert r.status_code == 200
    assert r.json()["completed_at"] is not None
    assert r.json()["is_done"] is True

    r = client.patch(f"/api/tasks/{task_id}", json={"is_done": False})
    assert r.status_code == 200
    assert r.json()["completed_at"] is None
    assert r.json()["is_done"] is False


def test_update_task_publishes_task_upsert(_test_db):
    from app.chat import pubsub
    from app.tasks import service
    from app.tasks.schemas import TaskCreate, TaskUpdate

    Session = _test_db
    with Session() as s:
        task = service.create_task(s, TaskCreate(title="Live task"))
        task_id = task.id
        chat_id = task.chat_session_id

    async def run() -> None:
        async with pubsub.subscribe(chat_id) as q:
            with Session() as s:
                service.update_task(s, task_id, TaskUpdate(title="Renamed task"))
            event = await asyncio.wait_for(q.get(), timeout=1.0)
            assert event["type"] == "task_upsert"
            assert event["session_id"] == chat_id
            assert event["task_id"] == task_id
            assert event["task"]["id"] == task_id
            assert event["task"]["title"] == "Renamed task"

    asyncio.run(run())


def test_patch_assignee_toggle(client):
    create = client.post("/api/tasks", json={"title": "Handoff"})
    task_id = create.json()["id"]
    assert create.json()["assignee"] == "user"

    r = client.patch(f"/api/tasks/{task_id}", json={"assignee": "assistant"})
    assert r.status_code == 200
    assert r.json()["assignee"] == "assistant"

    r = client.patch(f"/api/tasks/{task_id}", json={"assignee": "user"})
    assert r.status_code == 200
    assert r.json()["assignee"] == "user"


def test_patch_rejects_invalid_assignee(client):
    create = client.post("/api/tasks", json={"title": "X"})
    task_id = create.json()["id"]
    r = client.patch(f"/api/tasks/{task_id}", json={"assignee": "bot"})
    assert r.status_code == 422


def test_patch_interval_pair_validation(client):
    create = client.post("/api/tasks", json={"title": "Maybe recur"})
    task_id = create.json()["id"]

    r = client.patch(f"/api/tasks/{task_id}", json={"interval_unit": "week"})
    assert r.status_code == 422

    r = client.patch(
        f"/api/tasks/{task_id}",
        json={"interval_unit": "week", "interval_count": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["interval_unit"] == "week"
    assert body["interval_count"] == 1

    r = client.patch(
        f"/api/tasks/{task_id}",
        json={"interval_unit": None, "interval_count": None},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["interval_unit"] is None
    assert body["interval_count"] is None


def test_patch_missing_task_returns_404(client):
    r = client.patch("/api/tasks/9999", json={"is_done": True})
    assert r.status_code == 404


def test_run_now_brings_do_at_to_present(client, monkeypatch):
    """POST /tasks/{id}/run-now sets do_at to now and triggers a wake."""
    from app.chat import runner

    calls: list[int] = []
    monkeypatch.setattr(runner, "schedule_wake", lambda sid: calls.append(sid))

    create = client.post(
        "/api/tasks",
        json={
            "title": "Future scheduled job",
            "assignee": "assistant",
            "do_at": "2099-04-27T14:30:00",
        },
    )
    assert create.status_code == 201
    task_id = create.json()["id"]
    chat_id = create.json()["chat_session_id"]
    assert create.json()["state"] == "up_next"
    calls.clear()  # ignore the wake from creation, if any

    r = client.post(f"/api/tasks/{task_id}/run-now")
    assert r.status_code == 200
    body = r.json()
    # do_at moved into the past (or present) — task is now eligible.
    assert body["state"] == "running"
    assert calls == [chat_id]


def test_run_now_rejects_user_task(client):
    create = client.post("/api/tasks", json={"title": "Mine"})
    task_id = create.json()["id"]
    r = client.post(f"/api/tasks/{task_id}/run-now")
    assert r.status_code == 409


def test_run_now_rejects_done_task(client, monkeypatch):
    from app.chat import runner

    monkeypatch.setattr(runner, "schedule_wake", lambda sid: None)
    create = client.post(
        "/api/tasks",
        json={
            "title": "Done one",
            "assignee": "assistant",
            "do_at": "2099-04-27T14:30:00",
        },
    )
    task_id = create.json()["id"]
    client.patch(f"/api/tasks/{task_id}", json={"is_done": True})
    r = client.post(f"/api/tasks/{task_id}/run-now")
    assert r.status_code == 409


def test_run_now_missing_task_returns_404(client):
    r = client.post("/api/tasks/9999/run-now")
    assert r.status_code == 404


def test_delete_task(client):
    create = client.post("/api/tasks", json={"title": "Soon gone"})
    task_id = create.json()["id"]

    r = client.delete(f"/api/tasks/{task_id}")
    assert r.status_code == 204

    # Subsequent GET omits it.
    assert client.get("/api/tasks").json()["tasks"] == []


def test_delete_task_publishes_task_delete(_test_db):
    from app.chat import pubsub
    from app.tasks import service
    from app.tasks.schemas import TaskCreate

    Session = _test_db
    with Session() as s:
        task = service.create_task(s, TaskCreate(title="Gone soon"))
        task_id = task.id
        chat_id = task.chat_session_id

    async def run() -> None:
        async with pubsub.subscribe(chat_id) as q:
            with Session() as s:
                assert service.delete_task(s, task_id) is True
            event = await asyncio.wait_for(q.get(), timeout=1.0)
            assert event == {
                "type": "task_delete",
                "session_id": chat_id,
                "task_id": task_id,
            }

    asyncio.run(run())


def test_delete_missing_task_404(client):
    r = client.delete("/api/tasks/9999")
    assert r.status_code == 404


def test_delete_task_also_drops_chat_session(client):
    """Service-level cascade: deleting a task should not leave its
    chat session (or any messages it accumulated) orphaned."""
    from app.chat.models import ChatSession, Message  # noqa: F401
    from app.db import SessionLocal
    from tests._message_factory import make_message

    create = client.post("/api/tasks", json={"title": "Has chat"})
    body = create.json()
    task_id = body["id"]
    chat_id = body["chat_session_id"]

    with SessionLocal() as s:
        s.add(
            make_message(
                session_id=chat_id,
                kind="response",
                parts_json={"parts": [{"part_kind": "text", "content": "hi"}]},
            )
        )
        s.commit()
        assert s.get(ChatSession, chat_id) is not None

    r = client.delete(f"/api/tasks/{task_id}")
    assert r.status_code == 204

    with SessionLocal() as s:
        assert s.get(ChatSession, chat_id) is None
        assert s.query(Message).filter(Message.session_id == chat_id).count() == 0


def test_delete_chat_session_also_drops_task(client):
    """Reverse cascade: deleting the 1-to-1 chat session must drop the
    task too, so we can't end up with a task that has no chat (which
    would be permanently unrunnable). Mirrors the no-session repair
    invariant — both ends are CASCADE."""
    from app.chat.models import ChatSession
    from app.db import SessionLocal
    from app.tasks.models import Task

    create = client.post("/api/tasks", json={"title": "Soon orphaned"})
    body = create.json()
    task_id = body["id"]
    chat_id = body["chat_session_id"]

    with SessionLocal() as s:
        s.execute(ChatSession.__table__.delete().where(ChatSession.id == chat_id))
        s.commit()
        assert s.get(Task, task_id) is None


def test_get_task_by_id(client):
    create = client.post("/api/tasks", json={"title": "Look at me"})
    task_id = create.json()["id"]
    chat_id = create.json()["chat_session_id"]

    r = client.get(f"/api/tasks/{task_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == task_id
    assert body["title"] == "Look at me"
    assert body["chat_session_id"] == chat_id


def test_get_missing_task_404(client):
    r = client.get("/api/tasks/9999")
    assert r.status_code == 404


def test_task_direct_orm_mutation_refreshes_updated_at(client, monkeypatch):
    from app.db import SessionLocal
    from app.tasks import models as task_models
    from app.tasks.models import Task

    created = client.post("/api/tasks", json={"title": "Counter touch"}).json()
    stamped = datetime(2030, 1, 2, 3, 4, 5)
    monkeypatch.setattr(task_models, "utc_now", lambda: stamped)

    with SessionLocal() as s:
        task = s.get(Task, created["id"])
        assert task is not None
        assert task.updated_at != stamped
        task.consecutive_stalls += 1
        s.commit()
        s.refresh(task)
        assert task.updated_at == stamped


def test_activity_returns_stalled_and_errored_buckets(client):
    from app.db import SessionLocal
    from app.tasks.models import Task

    create = client.post("/api/tasks", json={"title": "Stalled one", "assignee": "assistant"})
    stalled_chat = create.json()["chat_session_id"]
    stalled_id = create.json()["id"]

    create = client.post("/api/tasks", json={"title": "Errored one", "assignee": "assistant"})
    errored_chat = create.json()["chat_session_id"]
    errored_id = create.json()["id"]

    with SessionLocal() as s:
        s.get(Task, stalled_id).consecutive_stalls = 2
        s.get(Task, errored_id).consecutive_errors = 1
        s.commit()

    r = client.get("/api/tasks/activity")
    assert r.status_code == 200
    body = r.json()
    assert stalled_chat in body["stalled_session_ids"]
    assert errored_chat in body["errored_session_ids"]
    assert stalled_chat not in body["errored_session_ids"]
    assert errored_chat not in body["stalled_session_ids"]
    # Empty `active_session_ids` is fine — no wake is mid-flight in the test.
    assert "active_session_ids" in body
