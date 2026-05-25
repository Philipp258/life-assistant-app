"""Tests for /api/settings/runtime."""

from __future__ import annotations

from fastapi.testclient import TestClient

EMPTY_RUNTIME_SETTINGS = {
    "brave_api_key": "",
    "vad_timeout_ms": "",
    "voice_playback_speed": "",
}


def test_get_runtime_settings_initially_empty(client: TestClient) -> None:
    r = client.get("/api/settings/runtime")
    assert r.status_code == 200, r.text
    assert r.json() == EMPTY_RUNTIME_SETTINGS


def test_put_runtime_setting_round_trip(client: TestClient) -> None:
    r = client.put(
        "/api/settings/runtime/brave_api_key",
        json={"value": "brave-test-key"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"key": "brave_api_key", "value": "brave-test-key"}

    r = client.get("/api/settings/runtime")
    assert r.status_code == 200
    assert r.json() == {**EMPTY_RUNTIME_SETTINGS, "brave_api_key": "brave-test-key"}


def test_put_can_clear_value(client: TestClient) -> None:
    client.put("/api/settings/runtime/brave_api_key", json={"value": "brave-test-key"})
    r = client.put("/api/settings/runtime/brave_api_key", json={"value": ""})
    assert r.status_code == 200
    assert r.json() == {"key": "brave_api_key", "value": ""}

    r = client.get("/api/settings/runtime")
    assert r.json() == EMPTY_RUNTIME_SETTINGS


def test_put_vad_timeout_setting_round_trip(client: TestClient) -> None:
    r = client.put(
        "/api/settings/runtime/vad_timeout_ms",
        json={"value": "1250"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"key": "vad_timeout_ms", "value": "1250"}

    r = client.get("/api/settings/runtime")
    assert r.status_code == 200
    assert r.json() == {**EMPTY_RUNTIME_SETTINGS, "vad_timeout_ms": "1250"}


def test_put_vad_timeout_rejects_invalid_values(client: TestClient) -> None:
    r = client.put("/api/settings/runtime/vad_timeout_ms", json={"value": "soon"})
    assert r.status_code == 404


def test_unknown_runtime_setting_returns_404(client: TestClient) -> None:
    r = client.put("/api/settings/runtime/unknown", json={"value": "x"})
    assert r.status_code == 404


def test_runtime_settings_require_auth(unauthed_client: TestClient) -> None:
    assert unauthed_client.get("/api/settings/runtime").status_code == 401
    assert (
        unauthed_client.put("/api/settings/runtime/brave_api_key", json={"value": "x"}).status_code
        == 401
    )
