"""Credentials are verified before they're stored.

Regression cover for the "stuck onboarding" trap: a wrong credential
used to be stored anyway, which flipped `/api/identity` to
`needs_chat` (agent can't start, no way back). Verification must reject
it at submit time so the state never advances.
"""

from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.provider_settings import verify as credential_verify


@pytest.fixture
def stuck_setup(db_session: Session) -> None:
    """Clear seeded creds and reset onboarding → state is `needs_provider`."""
    from app.provider_settings.models import ProviderSettings
    from app.users.models import User

    row = db_session.get(ProviderSettings, 1)
    assert row is not None
    row.preferred_chat_provider = None
    row.zai_api_key = None
    row.codex_auth_json = None
    user = db_session.query(User).first()
    assert user is not None
    user.onboarded_at = None
    db_session.commit()


def _state(client: TestClient) -> str:
    r = client.get("/api/identity")
    assert r.status_code == 200, r.text
    return r.json()["onboarding_state"]


def _fake_response(status_code: int) -> object:
    return types.SimpleNamespace(status_code=status_code)


def test_garbled_codex_blob_rejected_and_state_unchanged(
    client: TestClient, stuck_setup: None
) -> None:
    """The exact bug: a wrong Codex paste must not trap the user in chat."""
    assert _state(client) == "needs_provider"

    r = client.put(
        "/api/settings/providers/codex",
        json={"auth_json": "this is not the auth.json blob", "chat_model": "gpt-5-codex"},
    )

    assert r.status_code == 400, r.text
    assert "Codex" in r.json()["detail"]
    # Nothing stored, so we're still on step 1 — not trapped in chat.
    assert _state(client) == "needs_provider"
    assert client.get("/api/settings/providers").json()["codex"]["configured"] is False


def test_clearing_codex_skips_verification(client: TestClient, stuck_setup: None) -> None:
    """An empty string means "clear" — never run (or fail) verification."""
    r = client.put("/api/settings/providers/codex", json={"auth_json": ""})
    assert r.status_code == 200, r.text
    assert r.json()["codex"]["configured"] is False


def test_model_only_patch_skips_verification(
    client: TestClient, stuck_setup: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patching just the model (api/auth field omitted) must not verify."""

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("verification ran for a model-only patch")

    monkeypatch.setattr(credential_verify, "verify_codex", _boom)
    r = client.put("/api/settings/providers/codex", json={"chat_model": "gpt-5-codex"})
    assert r.status_code == 200, r.text


def test_openai_key_rejected_on_401(
    client: TestClient, stuck_setup: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credential_verify.httpx, "get", lambda *a, **k: _fake_response(401))
    r = client.put(
        "/api/settings/providers/openai",
        json={"api_key": "sk-wrong", "chat_model": "gpt-5.1"},
    )
    assert r.status_code == 400, r.text
    assert _state(client) == "needs_provider"


def test_openai_key_accepted_when_provider_ok(
    client: TestClient, stuck_setup: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credential_verify.httpx, "get", lambda *a, **k: _fake_response(200))
    r = client.put(
        "/api/settings/providers/openai",
        json={"api_key": "sk-good", "chat_model": "gpt-5.1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["openai"]["configured"] is True
    # Provider configured + still onboarding → advance to chat step.
    assert _state(client) == "needs_chat"


def test_unreachable_provider_does_not_block_key(
    client: TestClient, stuck_setup: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network failure can't disprove the key — don't punish the user."""

    def _raise(*_a: object, **_k: object) -> None:
        raise credential_verify.httpx.ConnectError("boom")

    monkeypatch.setattr(credential_verify.httpx, "get", _raise)
    r = client.put(
        "/api/settings/providers/openrouter",
        json={"api_key": "sk-or", "chat_model": "openrouter/auto"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["openrouter"]["configured"] is True
