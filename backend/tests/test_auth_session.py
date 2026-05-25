"""Cookie-session auth: login, logout, gate behaviour."""

from __future__ import annotations


def test_health_open_without_cookie(unauthed_client):
    r = unauthed_client.get("/api/health")
    assert r.status_code == 200


def test_protected_route_unauthed(unauthed_client):
    r = unauthed_client.get("/api/identity")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


def test_login_success_sets_cookie(unauthed_client):
    r = unauthed_client.post("/api/auth/login", json={"password": "test-pass"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert "life_assistant_session" in unauthed_client.cookies


def test_login_wrong_password(unauthed_client):
    r = unauthed_client.post("/api/auth/login", json={"password": "nope"})
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_password"
    assert "life_assistant_session" not in unauthed_client.cookies


def test_login_missing_field(unauthed_client):
    r = unauthed_client.post("/api/auth/login", json={})
    assert r.status_code == 422


def test_logout_clears_session(unauthed_client):
    unauthed_client.post("/api/auth/login", json={"password": "test-pass"})
    assert unauthed_client.get("/api/auth/me").json()["authenticated"] is True

    r = unauthed_client.post("/api/auth/logout")
    assert r.status_code == 204

    assert unauthed_client.get("/api/auth/me").json()["authenticated"] is False
    assert unauthed_client.get("/api/identity").status_code == 401


def test_protected_route_authed(unauthed_client):
    unauthed_client.post("/api/auth/login", json={"password": "test-pass"})
    r = unauthed_client.get("/api/identity")
    assert r.status_code == 200
    assert "assistant_name" in r.json()


def test_me_endpoint_reflects_state(unauthed_client):
    assert unauthed_client.get("/api/auth/me").json() == {"authenticated": False}
    unauthed_client.post("/api/auth/login", json={"password": "test-pass"})
    assert unauthed_client.get("/api/auth/me").json() == {"authenticated": True}


def test_session_persists_across_requests(unauthed_client):
    unauthed_client.post("/api/auth/login", json={"password": "test-pass"})
    for _ in range(3):
        assert unauthed_client.get("/api/identity").status_code == 200


def test_tampered_cookie_rejected(unauthed_client):
    unauthed_client.post("/api/auth/login", json={"password": "test-pass"})
    cookie = unauthed_client.cookies.get("life_assistant_session")
    assert cookie
    # Replace the signature segment so itsdangerous rejects it.
    head, _, _ = cookie.rpartition(".")
    unauthed_client.cookies.clear()
    unauthed_client.cookies.set("life_assistant_session", head + ".bogus")
    r = unauthed_client.get("/api/identity")
    assert r.status_code == 401


def test_login_cookie_attributes(unauthed_client):
    r = unauthed_client.post("/api/auth/login", json={"password": "test-pass"})
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "life_assistant_session=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=" in set_cookie
