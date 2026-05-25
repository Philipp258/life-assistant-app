"""HTTP-level tests for the /api/push/* endpoints."""

from __future__ import annotations

import pytest  # noqa: F401  (autouse fixture below uses pytest implicitly)


def _setup_vapid(monkeypatch):
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "vapid_public_key", "PUB", raising=True)
    monkeypatch.setattr(_settings, "vapid_private_key_path", "data/vapid_private.pem", raising=True)
    monkeypatch.setattr(_settings, "vapid_contact_email", "mailto:test@example.com", raising=True)


def test_vapid_public_key_returns_configured_value(client, monkeypatch):
    _setup_vapid(monkeypatch)
    r = client.get("/api/push/vapid-public-key")
    assert r.status_code == 200, r.text
    assert r.json() == {"key": "PUB"}


def test_vapid_public_key_503_when_unconfigured(client, monkeypatch):
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "vapid_public_key", None, raising=True)
    r = client.get("/api/push/vapid-public-key")
    assert r.status_code == 503


def test_subscribe_creates_row(client):
    payload = {
        "endpoint": "https://push.example/abc",
        "keys": {"p256dh": "P", "auth": "A"},
    }
    r = client.post("/api/push/subscribe", json=payload)
    assert r.status_code == 201, r.text
    assert isinstance(r.json()["id"], int)


def test_subscribe_is_idempotent_by_endpoint(client, db_session):
    from app.notifications.models import PushSubscription

    payload = {
        "endpoint": "https://push.example/abc",
        "keys": {"p256dh": "P1", "auth": "A1"},
    }
    r1 = client.post("/api/push/subscribe", json=payload)
    assert r1.status_code == 201
    id1 = r1.json()["id"]

    payload2 = {
        "endpoint": "https://push.example/abc",
        "keys": {"p256dh": "P2", "auth": "A2"},
    }
    r2 = client.post("/api/push/subscribe", json=payload2)
    assert r2.status_code == 201
    id2 = r2.json()["id"]

    assert id1 == id2
    rows = db_session.query(PushSubscription).all()
    assert len(rows) == 1
    assert rows[0].p256dh == "P2"
    assert rows[0].auth == "A2"
    assert rows[0].last_seen_at is not None


def test_unsubscribe_removes_row(client, db_session):
    from app.notifications.models import PushSubscription

    client.post(
        "/api/push/subscribe",
        json={
            "endpoint": "https://push.example/xyz",
            "keys": {"p256dh": "P", "auth": "A"},
        },
    )
    r = client.request(
        "DELETE",
        "/api/push/subscribe",
        json={"endpoint": "https://push.example/xyz"},
    )
    assert r.status_code == 204
    assert db_session.query(PushSubscription).count() == 0


def test_subscribe_unauthed_401(unauthed_client):
    r = unauthed_client.post(
        "/api/push/subscribe",
        json={
            "endpoint": "https://push.example/abc",
            "keys": {"p256dh": "P", "auth": "A"},
        },
    )
    assert r.status_code == 401


@pytest.fixture(autouse=True)
def _reset_dedupe():
    from app.notifications.service import _dedupe

    _dedupe.clear()
    yield
    _dedupe.clear()
