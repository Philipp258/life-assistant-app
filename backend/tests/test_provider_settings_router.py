"""Tests for /api/settings/providers."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def empty_settings(db_session: Session) -> None:
    """Clear the conftest-seeded singleton row so tests start clean."""
    from app.provider_settings.models import ProviderSettings

    row = db_session.get(ProviderSettings, 1)
    assert row is not None
    row.preferred_chat_provider = None
    row.openai_api_key = None
    row.openai_chat_model = None
    row.openrouter_api_key = None
    row.openrouter_chat_model = None
    row.openrouter_tts_model = None
    row.openrouter_tts_voice = None
    row.zai_api_key = None
    row.zai_endpoint = None
    row.zai_chat_model = None
    row.codex_auth_json = None
    row.codex_chat_model = None
    db_session.commit()


def test_get_returns_all_unconfigured_initially(client: TestClient, empty_settings: None) -> None:
    r = client.get("/api/settings/providers")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "preferred_chat_provider": None,
        "openai": {"configured": False, "chat_model": None},
        "openrouter": {
            "configured": False,
            "chat_model": None,
            "tts_model": None,
            "tts_voice": None,
        },
        "zai": {"configured": False, "endpoint": None, "chat_model": None},
        "codex": {"configured": False, "chat_model": None},
    }


def test_put_openai_round_trip(client: TestClient, empty_settings: None) -> None:
    r = client.put(
        "/api/settings/providers/openai",
        json={"api_key": "sk-openai", "chat_model": "gpt-5.1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["openai"] == {"configured": True, "chat_model": "gpt-5.1"}
    # GET round-trip.
    body = client.get("/api/settings/providers").json()
    assert body["openai"] == {"configured": True, "chat_model": "gpt-5.1"}


def test_put_openrouter_round_trip(client: TestClient, empty_settings: None) -> None:
    r = client.put(
        "/api/settings/providers/openrouter",
        json={
            "api_key": "sk-or",
            "chat_model": "openrouter/auto",
            "tts_model": "canopylabs/orpheus-3b-0.1-ft",
            "tts_voice": "leah",
        },
    )
    assert r.status_code == 200
    assert r.json()["openrouter"] == {
        "configured": True,
        "chat_model": "openrouter/auto",
        "tts_model": "canopylabs/orpheus-3b-0.1-ft",
        "tts_voice": "leah",
    }


def test_put_zai_with_endpoint(client: TestClient, empty_settings: None) -> None:
    r = client.put(
        "/api/settings/providers/zai",
        json={
            "api_key": "zai-key",
            "endpoint": "https://api.z.ai/api/coding/paas/v4",
            "chat_model": "glm-5.1",
        },
    )
    assert r.status_code == 200
    assert r.json()["zai"] == {
        "configured": True,
        "endpoint": "https://api.z.ai/api/coding/paas/v4",
        "chat_model": "glm-5.1",
    }


def test_put_codex_round_trip(client: TestClient, empty_settings: None) -> None:
    blob = '{"auth_mode":"chatgpt","tokens":{"access_token":"x","refresh_token":"y"}}'
    r = client.put(
        "/api/settings/providers/codex",
        json={"auth_json": blob, "chat_model": "gpt-5-codex"},
    )
    assert r.status_code == 200
    assert r.json()["codex"] == {"configured": True, "chat_model": "gpt-5-codex"}


def test_put_omitted_api_key_preserves_existing(client: TestClient, empty_settings: None) -> None:
    client.put(
        "/api/settings/providers/zai",
        json={"api_key": "first", "chat_model": "glm-5.1"},
    )
    r = client.put(
        "/api/settings/providers/zai",
        json={"chat_model": "glm-4.6"},
    )
    assert r.status_code == 200
    assert r.json()["zai"]["chat_model"] == "glm-4.6"

    from app.db import SessionLocal
    from app.provider_settings import service

    with SessionLocal() as db:
        row = service.get_settings(db)
    assert row.zai_api_key == "first"


def test_put_empty_string_clears_key(client: TestClient, empty_settings: None) -> None:
    client.put(
        "/api/settings/providers/zai",
        json={"api_key": "to-be-cleared", "chat_model": "glm-5.1"},
    )
    r = client.put(
        "/api/settings/providers/zai",
        json={"api_key": ""},
    )
    assert r.status_code == 200
    assert r.json()["zai"]["configured"] is False


def test_secrets_never_echoed(client: TestClient, empty_settings: None) -> None:
    r = client.put(
        "/api/settings/providers/openai",
        json={"api_key": "sk-super-secret", "chat_model": "gpt-5.1"},
    )
    assert "sk-super-secret" not in r.text
    r = client.get("/api/settings/providers")
    assert "sk-super-secret" not in r.text


def test_put_rejects_multiline_api_key(client: TestClient, empty_settings: None) -> None:
    """Pasting a Codex auth.json blob into the OpenRouter key field would
    otherwise be persisted and later sent as `Authorization: Bearer …`,
    where httpx surfaces the entire credential in a `LocalProtocolError`
    log. Block it at validation time. (See issue #129.)"""
    blob = '{\n  "auth_mode": "chatgpt",\n  "tokens": {"access_token": "x"}\n}'
    r = client.put(
        "/api/settings/providers/openrouter",
        json={"api_key": blob},
    )
    assert r.status_code == 422
    # The configured flag should still be False — nothing got persisted.
    body = client.get("/api/settings/providers").json()
    assert body["openrouter"]["configured"] is False


def test_put_rejects_api_key_with_control_chars(client: TestClient, empty_settings: None) -> None:
    r = client.put(
        "/api/settings/providers/openai",
        json={"api_key": "sk-foo\tbar"},
    )
    assert r.status_code == 422


def test_put_strips_whitespace_around_api_key(client: TestClient, empty_settings: None) -> None:
    r = client.put(
        "/api/settings/providers/openai",
        json={"api_key": "  sk-padded  "},
    )
    assert r.status_code == 200

    from app.db import SessionLocal
    from app.provider_settings import service

    with SessionLocal() as db:
        row = service.get_settings(db)
    assert row.openai_api_key == "sk-padded"


def test_put_codex_still_accepts_multiline_blob(client: TestClient, empty_settings: None) -> None:
    """The validator only applies to single-line API keys; Codex's
    `auth_json` is intentionally a multi-line JSON blob."""
    blob = (
        '{\n  "auth_mode": "chatgpt",\n  "tokens": {"access_token": "x", "refresh_token": "y"}\n}'
    )
    r = client.put(
        "/api/settings/providers/codex",
        json={"auth_json": blob, "chat_model": "gpt-5-codex"},
    )
    assert r.status_code == 200


def test_put_preferred_chat(client: TestClient, empty_settings: None) -> None:
    client.put(
        "/api/settings/providers/openai",
        json={"api_key": "sk-openai", "chat_model": "gpt-5.1"},
    )
    r = client.put(
        "/api/settings/providers/preferred-chat",
        json={"preferred_chat_provider": "openai"},
    )
    assert r.status_code == 200
    assert r.json()["preferred_chat_provider"] == "openai"


def test_put_preferred_chat_rejects_unconfigured(client: TestClient, empty_settings: None) -> None:
    r = client.put(
        "/api/settings/providers/preferred-chat",
        json={"preferred_chat_provider": "openai"},
    )
    assert r.status_code == 400
    assert "openai" in r.json()["detail"]


def test_put_preferred_chat_clears(client: TestClient, empty_settings: None) -> None:
    client.put(
        "/api/settings/providers/openai",
        json={"api_key": "sk-openai", "chat_model": None},
    )
    client.put(
        "/api/settings/providers/preferred-chat",
        json={"preferred_chat_provider": "openai"},
    )
    r = client.put(
        "/api/settings/providers/preferred-chat",
        json={"preferred_chat_provider": None},
    )
    assert r.status_code == 200
    assert r.json()["preferred_chat_provider"] is None


def test_get_ignores_stale_removed_preferred_provider(
    client: TestClient, db_session: Session, empty_settings: None
) -> None:
    from app.provider_settings import service

    row = service.get_settings(db_session)
    row.preferred_chat_provider = "removed-provider"
    db_session.commit()

    r = client.get("/api/settings/providers")
    assert r.status_code == 200, r.text
    assert r.json()["preferred_chat_provider"] is None


def test_get_requires_auth(unauthed_client: TestClient) -> None:
    r = unauthed_client.get("/api/settings/providers")
    assert r.status_code == 401


def test_put_requires_auth(unauthed_client: TestClient) -> None:
    r = unauthed_client.put(
        "/api/settings/providers/zai",
        json={"api_key": "k", "chat_model": "glm-5.1"},
    )
    assert r.status_code == 401


def test_legacy_singular_alias_returns_same_payload(
    client: TestClient, empty_settings: None
) -> None:
    """Stale frontend bundles call the old singular path. The alias keeps
    Settings working until those clients refresh. (See issue #156.)"""
    legacy = client.get("/api/settings/provider")
    current = client.get("/api/settings/providers")
    assert legacy.status_code == 200, legacy.text
    assert legacy.headers["content-type"].startswith("application/json")
    assert legacy.json() == current.json()


def test_unknown_api_route_returns_json_404(client: TestClient) -> None:
    """Unknown /api/... paths must not fall through to the SPA HTML —
    otherwise stale callers crash on `response.json()`. (See issue #156.)"""
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"detail": "Not Found"}
