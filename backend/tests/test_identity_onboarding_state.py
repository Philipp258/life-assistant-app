"""Tests for the 3-state onboarding machine on /api/identity."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def _identity(client: TestClient) -> dict:
    r = client.get("/api/identity")
    assert r.status_code == 200, r.text
    return r.json()


def test_state_needs_provider_when_unconfigured(client: TestClient, db_session: Session) -> None:
    # The conftest seeds a provider_settings row with zai creds so
    # chat-path tests can build the agent. Clear the creds here to
    # observe the empty state.
    from app.provider_settings.models import ProviderSettings

    row = db_session.get(ProviderSettings, 1)
    assert row is not None
    row.zai_api_key = None
    row.preferred_chat_provider = None
    db_session.commit()

    body = _identity(client)
    assert body["onboarding_state"] == "needs_provider"
    assert body["is_onboarding"] is True


def test_state_needs_chat_after_provider_set(client: TestClient, db_session: Session) -> None:
    # The conftest seeds the user with onboarded_at=now() to keep most
    # tests post-onboarding; reset it so we can observe the middle state.
    from app.users.models import User

    user = db_session.query(User).first()
    assert user is not None
    user.onboarded_at = None
    db_session.commit()

    body = _identity(client)
    assert body["onboarding_state"] == "needs_chat"
    assert body["is_onboarding"] is True


def test_state_done_when_provider_set_and_user_onboarded(
    client: TestClient,
) -> None:
    body = _identity(client)
    assert body["onboarding_state"] == "done"
    assert body["is_onboarding"] is False
