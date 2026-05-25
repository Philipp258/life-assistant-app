"""Filter-blob behaviour on `GET /api/tasks`.

Plan 2 Task 5 generalizes the listing endpoint to accept the same shape
that saved views serialize: labels, assignee, statuses (repeatable), and
a due window. Each test exercises one slice of the blob.
"""

from __future__ import annotations


def _seed(client):
    client.post("/api/labels", json={"slug": "home", "name": "Home"})
    client.post("/api/tasks", json={"title": "open-home", "labels": ["home"]})
    created = client.post(
        "/api/tasks",
        json={"title": "done-home", "labels": ["home"]},
    ).json()
    client.patch(f"/api/tasks/{created['id']}", json={"is_done": True})


def test_filter_by_status_only(client):
    _seed(client)
    resp = client.get("/api/tasks", params=[("status", "open")])
    titles = [t["title"] for t in resp.json()["tasks"]]
    assert "open-home" in titles
    assert "done-home" not in titles


def test_filter_by_label_and_assignee(client):
    _seed(client)
    resp = client.get(
        "/api/tasks",
        params=[("label", "home"), ("assignee", "user")],
    )
    titles = [t["title"] for t in resp.json()["tasks"]]
    assert "open-home" in titles


def test_filter_by_due_today_smoke(client):
    resp = client.get("/api/tasks", params=[("due", "today")])
    assert resp.status_code == 200
