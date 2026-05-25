"""PATCH /api/identity updates assistant_name / user_name in app_settings."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_patch_sets_both_names(client: TestClient) -> None:
    r = client.patch(
        "/api/identity",
        json={"assistant_name": "Atlas", "user_name": "Phil"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assistant_name"] == "Atlas"
    assert body["user_name"] == "Phil"

    again = client.get("/api/identity").json()
    assert again["assistant_name"] == "Atlas"
    assert again["user_name"] == "Phil"


def test_patch_partial_update(client: TestClient) -> None:
    r = client.patch("/api/identity", json={"assistant_name": "Nova"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assistant_name"] == "Nova"
    # conftest seed value untouched
    assert body["user_name"] == "Phil"


def test_patch_strips_whitespace(client: TestClient) -> None:
    r = client.patch(
        "/api/identity",
        json={"assistant_name": "  Atlas  ", "user_name": "  Phil  "},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["assistant_name"] == "Atlas"
    assert body["user_name"] == "Phil"


def test_patch_rejects_empty(client: TestClient) -> None:
    r = client.patch("/api/identity", json={"assistant_name": ""})
    assert r.status_code == 422


def test_patch_rejects_too_long(client: TestClient) -> None:
    r = client.patch("/api/identity", json={"user_name": "x" * 65})
    assert r.status_code == 422


def test_patch_requires_at_least_one_field(client: TestClient) -> None:
    r = client.patch("/api/identity", json={})
    assert r.status_code == 422


def test_patch_requires_auth(unauthed_client: TestClient) -> None:
    r = unauthed_client.patch("/api/identity", json={"assistant_name": "Atlas"})
    assert r.status_code == 401


def test_get_returns_both_names(client: TestClient) -> None:
    body = client.get("/api/identity").json()
    assert body["assistant_name"] == "Atlas"
    assert body["user_name"] == "Phil"
    assert body["onboarding_state"] == "done"
