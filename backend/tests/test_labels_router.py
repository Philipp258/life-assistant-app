"""End-to-end tests for the Labels HTTP API."""

from __future__ import annotations


def test_create_then_list_label(client):
    resp = client.post("/api/labels", json={"slug": "lab-1", "name": "Lab 1"})
    assert resp.status_code == 201, resp.text
    label_id = resp.json()["id"]

    listing = client.get("/api/labels").json()["labels"]
    assert any(item["id"] == label_id and item["slug"] == "lab-1" for item in listing)


def test_create_label_duplicate_slug_returns_409(client):
    client.post("/api/labels", json={"slug": "dup", "name": "Dup A"})
    resp = client.post("/api/labels", json={"slug": "dup", "name": "Dup B"})
    assert resp.status_code == 409


def test_patch_label_name(client):
    created = client.post("/api/labels", json={"slug": "rn-1", "name": "Old"}).json()
    resp = client.patch(f"/api/labels/{created['id']}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


def test_delete_label_clears_join_rows(client):
    label = client.post("/api/labels", json={"slug": "del-1", "name": "Del"}).json()
    task = client.post(
        "/api/tasks",
        json={"title": "x", "labels": ["del-1"]},
    ).json()
    resp = client.delete(f"/api/labels/{label['id']}")
    assert resp.status_code == 204
    after = client.get(f"/api/tasks/{task['id']}").json()
    assert after["labels"] == []
