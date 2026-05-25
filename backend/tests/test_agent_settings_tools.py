"""Tests for the assistant-facing app-settings tools."""

from __future__ import annotations

from app.agent.tools import settings as settings_tools

EMPTY_RUNTIME_SETTINGS = {
    "brave_api_key": "",
    "vad_timeout_ms": "",
    "voice_playback_speed": "",
}


def test_agent_settings_tools_round_trip(_test_db) -> None:
    settings_tools.set_runtime_setting("brave_api_key", "brave-agent-key")
    assert settings_tools.get_runtime_settings() == {
        **EMPTY_RUNTIME_SETTINGS,
        "brave_api_key": "brave-agent-key",
    }


def test_agent_settings_tools_empty_clears_value(_test_db) -> None:
    settings_tools.set_runtime_setting("brave_api_key", "brave-agent-key")
    settings_tools.set_runtime_setting("brave_api_key", "")
    assert settings_tools.get_runtime_settings() == EMPTY_RUNTIME_SETTINGS


def test_agent_settings_tools_reject_unknown_key(_test_db) -> None:
    out = settings_tools.set_runtime_setting("unknown", "x")
    assert "error" in out
    assert "Unsupported runtime setting" in out["error"]


def test_agent_settings_tools_default_value_is_empty_string(_test_db) -> None:
    assert settings_tools.get_runtime_settings() == EMPTY_RUNTIME_SETTINGS
