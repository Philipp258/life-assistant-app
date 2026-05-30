"""Filter-blob behaviour on `GET /api/tasks`.

Saved views serialize assignee, statuses (repeatable), and a due window.
Each test exercises one slice of the blob.
"""

from __future__ import annotations


def _seed(client):
    client.post("/api/tasks", json={"title": "open-mine", "assignee": "user"})
    created = client.post(
        "/api/tasks",
        json={"title": "done-mine", "assignee": "user"},
    ).json()
    client.patch(f"/api/tasks/{created['id']}", json={"is_done": True})


def test_filter_by_status_only(client):
    _seed(client)
    resp = client.get("/api/tasks", params=[("status", "open")])
    titles = [t["title"] for t in resp.json()["tasks"]]
    assert "open-mine" in titles
    assert "done-mine" not in titles


def test_filter_by_assignee(client):
    _seed(client)
    resp = client.get(
        "/api/tasks",
        params=[("assignee", "user")],
    )
    titles = [t["title"] for t in resp.json()["tasks"]]
    assert "open-mine" in titles


def test_filter_by_due_today_smoke(client):
    resp = client.get("/api/tasks", params=[("due", "today")])
    assert resp.status_code == 200
