"""Tests for app.provider_settings.service."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.provider_settings import service
from app.provider_settings.models import ProviderSettings


@pytest.fixture
def empty_settings(db_session: Session) -> None:
    """Clear all credentials on the conftest-seeded singleton row."""
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


def test_is_chat_configured_false_when_empty(db_session: Session, empty_settings: None) -> None:
    assert service.is_chat_configured() is False


def test_pick_chat_raises_when_empty(db_session: Session, empty_settings: None) -> None:
    with pytest.raises(service.NoProviderConfiguredError):
        service.pick_chat(db_session)


def test_update_openai_round_trip(db_session: Session, empty_settings: None) -> None:
    service.update_openai(db_session, api_key="sk-openai-test", chat_model="gpt-5.1")
    row = service.get_settings(db_session)
    assert row.openai_api_key == "sk-openai-test"
    assert row.openai_chat_model == "gpt-5.1"
    assert service.is_chat_configured() is True

    pick = service.pick_chat(db_session)
    assert pick.provider == "openai"
    assert pick.openai_api_key == "sk-openai-test"
    assert pick.model_name == "gpt-5.1"


def test_update_openrouter_round_trip(db_session: Session, empty_settings: None) -> None:
    service.update_openrouter(db_session, api_key="sk-or-test", chat_model="openrouter/auto")
    pick = service.pick_chat(db_session)
    assert pick.provider == "openrouter"
    assert pick.openrouter_api_key == "sk-or-test"
    assert pick.model_name == "openrouter/auto"


def test_update_zai_round_trip_with_endpoint(db_session: Session, empty_settings: None) -> None:
    service.update_zai(
        db_session,
        api_key="zai-key",
        endpoint="https://api.z.ai/api/coding/paas/v4",
        chat_model="glm-5.1",
    )
    pick = service.pick_chat(db_session)
    assert pick.provider == "zai"
    assert pick.zai_api_key == "zai-key"
    assert pick.zai_endpoint == "https://api.z.ai/api/coding/paas/v4"
    assert pick.model_name == "glm-5.1"


def test_update_codex_round_trip(db_session: Session, empty_settings: None) -> None:
    blob = '{"auth_mode":"chatgpt","tokens":{"access_token":"x","refresh_token":"y"}}'
    service.update_codex(db_session, auth_json=blob, chat_model="gpt-5.5")
    pick = service.pick_chat(db_session)
    assert pick.provider == "codex"
    assert pick.codex_auth_json == blob


def test_partial_update_preserves_other_field(db_session: Session, empty_settings: None) -> None:
    service.update_zai(db_session, api_key="zai-1", endpoint=None, chat_model="glm-5.1")
    # Update only the model — None for api_key means "leave alone".
    service.update_zai(db_session, api_key=None, endpoint=None, chat_model="glm-4.6")
    row = service.get_settings(db_session)
    assert row.zai_api_key == "zai-1"
    assert row.zai_chat_model == "glm-4.6"


def test_empty_string_clears_field(db_session: Session, empty_settings: None) -> None:
    service.update_openai(db_session, api_key="sk-1", chat_model="gpt-5.1")
    # Empty string = explicit clear.
    service.update_openai(db_session, api_key="", chat_model=None)
    row = service.get_settings(db_session)
    assert row.openai_api_key is None
    assert row.openai_chat_model == "gpt-5.1"


def test_default_model_used_when_user_model_unset(
    db_session: Session, empty_settings: None
) -> None:
    service.update_openrouter(db_session, api_key="sk-or", chat_model=None)
    pick = service.pick_chat(db_session)
    assert pick.model_name == "openrouter/auto"


def test_codex_default_model_matches_provider_constant(
    db_session: Session, empty_settings: None
) -> None:
    from app.agent.providers.codex import DEFAULT_CODEX_MODEL

    service.update_codex(db_session, auth_json="{}", chat_model=None)
    pick = service.pick_chat(db_session)

    assert pick.provider == "codex"
    assert pick.model_name == DEFAULT_CODEX_MODEL


def test_preferred_chat_honoured_when_configured(db_session: Session, empty_settings: None) -> None:
    service.update_openai(db_session, api_key="sk-openai", chat_model="gpt-5.1")
    service.update_zai(db_session, api_key="zai-k", endpoint=None, chat_model="glm-5.1")
    service.update_preferred_chat(db_session, preferred="zai")

    pick = service.pick_chat(db_session)
    assert pick.provider == "zai"


def test_preferred_chat_falls_through_when_unconfigured(
    db_session: Session, empty_settings: None
) -> None:
    """Preference points at an unconfigured provider → use hardcoded order."""
    row = service.get_settings(db_session)
    row.preferred_chat_provider = "codex"
    db_session.commit()
    service.update_zai(db_session, api_key="zai-k", endpoint=None, chat_model="glm-5.1")

    pick = service.pick_chat(db_session)
    assert pick.provider == "zai"  # codex not configured, falls through to zai


def test_preference_order_when_multiple_configured(
    db_session: Session, empty_settings: None
) -> None:
    """No explicit preference → order is openai, openrouter, zai, codex."""
    service.update_openrouter(db_session, api_key="sk-or", chat_model=None)
    service.update_zai(db_session, api_key="zai-k", endpoint=None, chat_model=None)

    pick = service.pick_chat(db_session)
    assert pick.provider == "openrouter"


def test_pick_tts_returns_none_when_no_openrouter(
    db_session: Session, empty_settings: None
) -> None:
    service.update_openai(db_session, api_key="sk-openai", chat_model=None)
    assert service.pick_tts(db_session) is None


def test_pick_tts_returns_openrouter_key_and_model(
    db_session: Session, empty_settings: None
) -> None:
    service.update_openrouter(
        db_session,
        api_key="sk-or-tts",
        chat_model=None,
        tts_model="canopylabs/orpheus-3b-0.1-ft",
        tts_voice="leah",
    )
    pick = service.pick_tts(db_session)
    assert pick is not None
    assert pick.api_key == "sk-or-tts"
    assert pick.model_name == "canopylabs/orpheus-3b-0.1-ft"
    assert pick.voice == "leah"


def test_pick_stt_requires_openrouter(db_session: Session, empty_settings: None) -> None:
    service.update_openai(db_session, api_key="sk-openai", chat_model=None)
    with pytest.raises(service.NoProviderConfiguredError):
        service.pick_stt(db_session)


def test_pick_stt_returns_openrouter_key(db_session: Session, empty_settings: None) -> None:
    service.update_openrouter(db_session, api_key="sk-or-stt", chat_model=None)
    pick = service.pick_stt(db_session)
    assert pick.api_key == "sk-or-stt"


def test_persist_codex_auth_updates_blob(db_session: Session, empty_settings: None) -> None:
    import asyncio

    service.update_codex(db_session, auth_json="initial-blob", chat_model=None)
    asyncio.run(service.persist_codex_auth("rotated-blob"))

    row = service.get_settings(db_session)
    assert row.codex_auth_json == "rotated-blob"


def test_persist_codex_auth_writes_even_if_provider_inactive(
    db_session: Session, empty_settings: None
) -> None:
    """Refresh callback should still write — it's keyed by row, not by preference."""
    import asyncio

    service.update_codex(db_session, auth_json="old", chat_model=None)
    service.update_zai(db_session, api_key="zai-k", endpoint=None, chat_model=None)
    service.update_preferred_chat(db_session, preferred="zai")

    asyncio.run(service.persist_codex_auth("new"))
    row = service.get_settings(db_session)
    assert row.codex_auth_json == "new"


def test_update_invalidates_agent_cache(db_session: Session, empty_settings: None) -> None:
    from app import agent as agent_module

    agent_module._agent = "sentinel"  # type: ignore[assignment]
    service.update_zai(db_session, api_key="k", endpoint=None, chat_model="glm-5.1")
    assert agent_module._agent is None
