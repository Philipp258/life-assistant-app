"""End-to-end tests for the tasks endpoint with label filtering and persistence."""

from __future__ import annotations


def _label(client, slug: str) -> int:
    return client.post("/api/labels", json={"slug": slug, "name": slug}).json()["id"]


def test_create_task_with_labels_returns_them(client):
    _label(client, "alpha")
    _label(client, "beta")
    resp = client.post("/api/tasks", json={"title": "x", "labels": ["alpha", "beta"]})
    assert resp.status_code == 201, resp.text
    assert set(resp.json()["labels"]) == {"alpha", "beta"}


def test_list_tasks_filtered_by_single_label(client):
    _label(client, "home")
    _label(client, "work")
    client.post("/api/tasks", json={"title": "a", "labels": ["home"]}).json()
    client.post("/api/tasks", json={"title": "b", "labels": ["work"]})
    resp = client.get("/api/tasks?label=home")
    titles = [t["title"] for t in resp.json()["tasks"]]
    assert "a" in titles and "b" not in titles


def test_list_tasks_filtered_by_multiple_labels_uses_or(client):
    _label(client, "red")
    _label(client, "blue")
    _label(client, "green")
    client.post("/api/tasks", json={"title": "r", "labels": ["red"]})
    client.post("/api/tasks", json={"title": "b", "labels": ["blue"]})
    client.post("/api/tasks", json={"title": "g", "labels": ["green"]})
    resp = client.get("/api/tasks?label=red&label=blue")
    titles = sorted(t["title"] for t in resp.json()["tasks"])
    assert titles == ["b", "r"]


def test_patch_task_replaces_labels(client):
    _label(client, "one")
    _label(client, "two")
    created = client.post("/api/tasks", json={"title": "x", "labels": ["one"]}).json()
    resp = client.patch(f"/api/tasks/{created['id']}", json={"labels": ["two"]})
    assert resp.json()["labels"] == ["two"]
