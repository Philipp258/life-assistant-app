"""Brute-force throttle on /api/auth/login.

Integration tests drive the HTTP path with the real clock; unit tests use
a fake clock so window/lockout boundaries are deterministic.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.auth import rate_limit


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    now = [1000.0]
    monkeypatch.setattr(rate_limit, "_now", lambda: now[0])
    rate_limit._reset_for_tests()
    yield now


def test_lockout_after_max_failures(unauthed_client):
    for _ in range(rate_limit.MAX_FAILURES):
        r = unauthed_client.post("/api/auth/login", json={"password": "nope"})
        assert r.status_code == 401
    r = unauthed_client.post("/api/auth/login", json={"password": "nope"})
    assert r.status_code == 429
    assert r.json()["detail"] == "too_many_attempts"
    assert int(r.headers["Retry-After"]) > 0


def test_correct_password_blocked_while_locked(unauthed_client):
    for _ in range(rate_limit.MAX_FAILURES):
        unauthed_client.post("/api/auth/login", json={"password": "nope"})
    r = unauthed_client.post("/api/auth/login", json={"password": "test-pass"})
    assert r.status_code == 429
    assert "life_assistant_session" not in unauthed_client.cookies


def test_success_resets_counter(unauthed_client):
    for _ in range(rate_limit.MAX_FAILURES - 1):
        r = unauthed_client.post("/api/auth/login", json={"password": "nope"})
        assert r.status_code == 401
    r = unauthed_client.post("/api/auth/login", json={"password": "test-pass"})
    assert r.status_code == 200
    unauthed_client.post("/api/auth/logout")
    # Fresh budget after success.
    for _ in range(rate_limit.MAX_FAILURES - 1):
        r = unauthed_client.post("/api/auth/login", json={"password": "nope"})
        assert r.status_code == 401


def test_window_expiry_releases_lock(fake_clock):
    for _ in range(rate_limit.MAX_FAILURES):
        rate_limit.register_failure("1.2.3.4")
    assert rate_limit.check_locked("1.2.3.4") is not None

    fake_clock[0] += rate_limit.LOCKOUT_SECONDS + 1
    assert rate_limit.check_locked("1.2.3.4") is None


def test_failures_outside_window_drop(fake_clock):
    for _ in range(rate_limit.MAX_FAILURES - 1):
        rate_limit.register_failure("1.2.3.4")
    fake_clock[0] += rate_limit.WINDOW_SECONDS + 1
    for _ in range(rate_limit.MAX_FAILURES - 1):
        rate_limit.register_failure("1.2.3.4")
    assert rate_limit.check_locked("1.2.3.4") is None


def test_independent_ips(fake_clock):
    for _ in range(rate_limit.MAX_FAILURES):
        rate_limit.register_failure("1.1.1.1")
    assert rate_limit.check_locked("1.1.1.1") is not None
    assert rate_limit.check_locked("2.2.2.2") is None


def test_register_success_releases_lock(fake_clock):
    for _ in range(rate_limit.MAX_FAILURES):
        rate_limit.register_failure("1.2.3.4")
    assert rate_limit.check_locked("1.2.3.4") is not None
    rate_limit.register_success("1.2.3.4")
    assert rate_limit.check_locked("1.2.3.4") is None
