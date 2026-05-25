"""Unit tests for app.notifications.service.notify fan-out logic."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.notifications.models import PushSubscription


def _seed_sub(db_session, endpoint: str = "https://push.example/abc") -> int:
    row = PushSubscription(endpoint=endpoint, p256dh="P", auth="A")
    db_session.add(row)
    db_session.commit()
    return row.id


def _enable_vapid(monkeypatch):
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "vapid_public_key", "PUB", raising=True)
    monkeypatch.setattr(_settings, "vapid_private_key_path", "data/vapid_private.pem", raising=True)
    monkeypatch.setattr(_settings, "vapid_contact_email", "mailto:test@example.com", raising=True)


@pytest.fixture(autouse=True)
def _reset_dedupe():
    from app.notifications.service import _dedupe, _warned_no_vapid  # noqa: F401

    _dedupe.clear()
    yield
    _dedupe.clear()


def test_notify_calls_send_one_per_subscription(db_session, monkeypatch):
    _enable_vapid(monkeypatch)
    _seed_sub(db_session, "https://push.example/a")
    _seed_sub(db_session, "https://push.example/b")

    from app.notifications import service

    calls: list[str] = []

    def fake_send_one(sub: PushSubscription, payload: dict[str, Any]) -> int | None:
        calls.append(sub.endpoint)
        return None

    monkeypatch.setattr(service, "_send_one", fake_send_one)

    asyncio.run(service.notify(event_type="t", title="T", body="B", url="/"))

    assert sorted(calls) == [
        "https://push.example/a",
        "https://push.example/b",
    ]


def test_notify_drops_410_subscriptions(db_session, monkeypatch):
    _enable_vapid(monkeypatch)
    _seed_sub(db_session, "https://push.example/dead")
    _seed_sub(db_session, "https://push.example/alive")

    from app.notifications import service

    def fake_send_one(sub: PushSubscription, _payload: dict[str, Any]) -> int | None:
        if "dead" in sub.endpoint:
            return 410
        return None

    monkeypatch.setattr(service, "_send_one", fake_send_one)

    asyncio.run(service.notify(event_type="t", title="T", body="B", url="/"))

    remaining = [r.endpoint for r in db_session.query(PushSubscription).all()]
    assert remaining == ["https://push.example/alive"]


def test_notify_keeps_subscription_on_500(db_session, monkeypatch):
    _enable_vapid(monkeypatch)
    _seed_sub(db_session, "https://push.example/flaky")

    from app.notifications import service

    monkeypatch.setattr(service, "_send_one", lambda _s, _p: 500)

    asyncio.run(service.notify(event_type="t", title="T", body="B", url="/"))

    assert db_session.query(PushSubscription).count() == 1


def test_notify_suppressed_when_session_has_subscriber(db_session, monkeypatch):
    _enable_vapid(monkeypatch)
    _seed_sub(db_session)

    from app.chat import pubsub
    from app.notifications import service

    calls: list[str] = []
    monkeypatch.setattr(service, "_send_one", lambda s, _p: calls.append(s.endpoint) or None)

    async def go() -> None:
        async with pubsub.subscribe(42):
            await service.notify(
                event_type="t",
                title="T",
                body="B",
                url="/",
                quiet_if_session_id=42,
            )

    asyncio.run(go())
    assert calls == []


def test_notify_fires_when_no_subscriber_for_session(db_session, monkeypatch):
    _enable_vapid(monkeypatch)
    _seed_sub(db_session)

    from app.notifications import service

    calls: list[str] = []
    monkeypatch.setattr(service, "_send_one", lambda s, _p: calls.append(s.endpoint) or None)

    asyncio.run(
        service.notify(
            event_type="t",
            title="T",
            body="B",
            url="/",
            quiet_if_session_id=99,
        )
    )
    assert len(calls) == 1


def test_notify_dedupe_skips_within_window(db_session, monkeypatch):
    _enable_vapid(monkeypatch)
    _seed_sub(db_session)

    from app.notifications import service

    calls: list[str] = []
    monkeypatch.setattr(service, "_send_one", lambda s, _p: calls.append(s.endpoint) or None)

    asyncio.run(service.notify(event_type="t", title="T", body="B", url="/", dedupe_key="k1"))
    asyncio.run(service.notify(event_type="t", title="T", body="B", url="/", dedupe_key="k1"))

    assert len(calls) == 1


def test_notify_no_op_when_vapid_unconfigured(db_session, monkeypatch):
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "vapid_public_key", None, raising=True)
    monkeypatch.setattr(_settings, "vapid_private_key_path", None, raising=True)
    monkeypatch.setattr(_settings, "vapid_contact_email", None, raising=True)
    _seed_sub(db_session)

    from app.notifications import service

    calls: list[Any] = []
    monkeypatch.setattr(service, "_send_one", lambda s, p: calls.append(s) or None)

    asyncio.run(service.notify(event_type="t", title="T", body="B", url="/"))
    assert calls == []
