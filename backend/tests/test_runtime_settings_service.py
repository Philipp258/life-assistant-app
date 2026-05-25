"""Tests for app.settings.service."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.settings import service

EMPTY_RUNTIME_SETTINGS = {
    "brave_api_key": "",
    "vad_timeout_ms": "",
    "voice_playback_speed": "",
}


def test_get_brave_api_key_returns_none_when_unset(db_session: Session) -> None:
    assert service.get_brave_api_key(db_session) is None


def test_set_then_get_brave_api_key(db_session: Session) -> None:
    service.set_runtime_setting(db_session, key="brave_api_key", value="brave-test-key")
    assert service.get_brave_api_key(db_session) == "brave-test-key"
    assert service.list_runtime_settings(db_session) == {
        **EMPTY_RUNTIME_SETTINGS,
        "brave_api_key": "brave-test-key",
    }


def test_set_replaces_existing_value(db_session: Session) -> None:
    service.set_runtime_setting(db_session, key="brave_api_key", value="first")
    service.set_runtime_setting(db_session, key="brave_api_key", value="second")
    assert service.get_brave_api_key(db_session) == "second"


def test_empty_string_clears_to_unconfigured(db_session: Session) -> None:
    service.set_runtime_setting(db_session, key="brave_api_key", value="brave-test-key")
    service.set_runtime_setting(db_session, key="brave_api_key", value="")
    assert service.get_brave_api_key(db_session) is None
    assert service.list_runtime_settings(db_session) == EMPTY_RUNTIME_SETTINGS


def test_whitespace_value_treated_as_unset(db_session: Session) -> None:
    service.set_runtime_setting(db_session, key="brave_api_key", value="   ")
    assert service.get_brave_api_key(db_session) is None


def test_list_includes_every_supported_key_with_defaults(db_session: Session) -> None:
    assert service.list_runtime_settings(db_session) == EMPTY_RUNTIME_SETTINGS


def test_set_then_list_vad_timeout_ms(db_session: Session) -> None:
    service.set_runtime_setting(db_session, key="vad_timeout_ms", value="1250")
    assert service.list_runtime_settings(db_session) == {
        **EMPTY_RUNTIME_SETTINGS,
        "vad_timeout_ms": "1250",
    }


def test_empty_vad_timeout_ms_clears_to_default(db_session: Session) -> None:
    service.set_runtime_setting(db_session, key="vad_timeout_ms", value="1250")
    service.set_runtime_setting(db_session, key="vad_timeout_ms", value="")
    assert service.list_runtime_settings(db_session) == EMPTY_RUNTIME_SETTINGS


def test_vad_timeout_ms_rejects_invalid_values(db_session: Session) -> None:
    with pytest.raises(ValueError, match="integer"):
        service.set_runtime_setting(db_session, key="vad_timeout_ms", value="soon")
    with pytest.raises(ValueError, match="between"):
        service.set_runtime_setting(db_session, key="vad_timeout_ms", value="10")


def test_set_then_list_voice_playback_speed(db_session: Session) -> None:
    service.set_runtime_setting(db_session, key="voice_playback_speed", value="1.15")
    assert service.list_runtime_settings(db_session) == {
        **EMPTY_RUNTIME_SETTINGS,
        "voice_playback_speed": "1.15",
    }


def test_empty_voice_playback_speed_clears_to_default(db_session: Session) -> None:
    service.set_runtime_setting(db_session, key="voice_playback_speed", value="1.15")
    service.set_runtime_setting(db_session, key="voice_playback_speed", value="")
    assert service.list_runtime_settings(db_session) == EMPTY_RUNTIME_SETTINGS


def test_voice_playback_speed_rejects_invalid_values(db_session: Session) -> None:
    with pytest.raises(ValueError, match="number"):
        service.set_runtime_setting(db_session, key="voice_playback_speed", value="fast")
    with pytest.raises(ValueError, match="finite"):
        service.set_runtime_setting(db_session, key="voice_playback_speed", value="inf")
    with pytest.raises(ValueError, match="between"):
        service.set_runtime_setting(db_session, key="voice_playback_speed", value="2.5")


def test_unknown_setting_rejected_on_set(db_session: Session) -> None:
    with pytest.raises(ValueError, match="Unsupported runtime setting"):
        service.set_runtime_setting(db_session, key="unknown", value="x")


def test_unknown_setting_rejected_on_get(db_session: Session) -> None:
    with pytest.raises(ValueError, match="Unsupported runtime setting"):
        service.get_runtime_setting(db_session, "unknown")
