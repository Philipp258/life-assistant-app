"""Router tests for /api/saved-task-views.

Uses the project's `client` fixture (see conftest.py) so each test gets an
isolated SQLite DB and the test session cookie is already set.
"""

from __future__ import annotations

from unittest.mock import patch


def test_default_view_listed(client):
    # Boot seeding is disabled for app-via-client tests. Create the default
    # view shape + mark default inside the test so the assertion is self-contained.
    body = {
        "name": "Tasks",
        "filters": {},
        "group_by": "none",
    }
    created = client.post("/api/saved-task-views", json=body).json()
    client.patch(f"/api/saved-task-views/{created['id']}", json={"is_default": True})
    items = client.get("/api/saved-task-views").json()["views"]
    assert any(v["name"] == "Tasks" and v["is_default"] for v in items)


def test_create_view(client):
    body = {
        "name": "Home",
        "icon": "\U0001f3e0",
        "filters": {"labels": ["home"]},
        "group_by": "none",
    }
    resp = client.post("/api/saved-task-views", json=body)
    assert resp.status_code == 201
    assert resp.json()["filters"]["labels"] == ["home"]


def test_patch_view(client):
    created = client.post(
        "/api/saved-task-views",
        json={"name": "Rev", "filters": {}, "group_by": "none"},
    ).json()
    resp = client.patch(f"/api/saved-task-views/{created['id']}", json={"name": "Review"})
    assert resp.json()["name"] == "Review"


def test_make_default_clears_existing_default(client):
    first = client.post(
        "/api/saved-task-views",
        json={"name": "First", "filters": {}, "group_by": "none"},
    ).json()
    client.patch(f"/api/saved-task-views/{first['id']}", json={"is_default": True})

    new_default = client.post(
        "/api/saved-task-views",
        json={"name": "Inbox", "filters": {}, "group_by": "none"},
    ).json()
    client.patch(f"/api/saved-task-views/{new_default['id']}", json={"is_default": True})

    items = client.get("/api/saved-task-views").json()["views"]
    defaults = [v for v in items if v["is_default"]]
    assert len(defaults) == 1 and defaults[0]["id"] == new_default["id"]


def test_delete_view(client):
    # Need 2 to avoid the last-remaining guard.
    client.post(
        "/api/saved-task-views",
        json={"name": "Keep", "filters": {}, "group_by": "none"},
    )
    created = client.post(
        "/api/saved-task-views",
        json={"name": "Tmp", "filters": {}, "group_by": "none"},
    ).json()
    resp = client.delete(f"/api/saved-task-views/{created['id']}")
    assert resp.status_code == 204


def test_cannot_delete_last_remaining_view(client):
    only = client.post(
        "/api/saved-task-views",
        json={"name": "Only", "filters": {}, "group_by": "none"},
    ).json()
    resp = client.delete(f"/api/saved-task-views/{only['id']}")
    assert resp.status_code == 409


def test_delete_default_view_promotes_next_view(client):
    a = client.post(
        "/api/saved-task-views",
        json={"name": "A", "icon": "a", "filters": {}, "group_by": "none"},
    ).json()
    b = client.post(
        "/api/saved-task-views",
        json={"name": "B", "icon": "b", "filters": {}, "group_by": "none"},
    ).json()
    # Make A the default explicitly (also clears any seeded default).
    client.patch(f"/api/saved-task-views/{a['id']}", json={"is_default": True})
    # Delete A.
    resp = client.delete(f"/api/saved-task-views/{a['id']}")
    assert resp.status_code == 204
    # Exactly one view is now default, and it's B (or whichever remaining view
    # has the lowest sort_index — A was created first, so B is next).
    items = client.get("/api/saved-task-views").json()["views"]
    defaults = [v for v in items if v["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == b["id"]


def test_patch_sort_index_changes_list_order(client):
    """PATCH sort_index lets the UI persist a tab order; the list endpoint
    must reflect it.

    The "reorder" UX in the tasks screen issues one PATCH per row with the
    new sort_index. Verify the round-trip: PATCH the indices for two new
    views in reverse order, then read them back and confirm the order
    flipped accordingly.
    """
    a = client.post(
        "/api/saved-task-views",
        json={"name": "Alpha", "filters": {}, "group_by": "none"},
    ).json()
    b = client.post(
        "/api/saved-task-views",
        json={"name": "Bravo", "filters": {}, "group_by": "none"},
    ).json()
    # Server assigns increasing sort_index on creation, so Alpha < Bravo.
    initial = client.get("/api/saved-task-views").json()["views"]
    initial_order = [v["name"] for v in initial if v["name"] in {"Alpha", "Bravo"}]
    assert initial_order == ["Alpha", "Bravo"]

    # Swap: Bravo before Alpha.
    client.patch(f"/api/saved-task-views/{b['id']}", json={"sort_index": 0})
    client.patch(f"/api/saved-task-views/{a['id']}", json={"sort_index": 1})

    final = client.get("/api/saved-task-views").json()["views"]
    swapped = [v["name"] for v in final if v["name"] in {"Alpha", "Bravo"}]
    assert swapped == ["Bravo", "Alpha"]


@patch("app.saved_task_views.router.pick_emoji_for_view", return_value="\U0001f3e0")
def test_create_uses_llm_for_icon_when_omitted(mock_pick, client):
    body = {"name": "Home", "filters": {"labels": ["home"]}, "group_by": "none"}
    resp = client.post("/api/saved-task-views", json=body)
    assert resp.status_code == 201
    assert resp.json()["icon"] == "\U0001f3e0"
    mock_pick.assert_called_once()


@patch("app.saved_task_views.router.pick_emoji_for_view", return_value="\U0001f3e0")
def test_create_keeps_explicit_icon(mock_pick, client):
    body = {"name": "Home", "icon": "\U0001f6d6", "filters": {}, "group_by": "none"}
    resp = client.post("/api/saved-task-views", json=body)
    assert resp.json()["icon"] == "\U0001f6d6"
    mock_pick.assert_not_called()


@patch("app.saved_task_views.router.pick_emoji_for_view", return_value=None)
def test_create_falls_back_to_null_icon_when_llm_fails(_mock, client):
    body = {"name": "Home", "filters": {}, "group_by": "none"}
    resp = client.post("/api/saved-task-views", json=body)
    assert resp.json()["icon"] is None
