"""Read/write the singleton ProviderSettings row + capability dispatch.

One row (id=1). Each provider has typed columns; nulls mean unconfigured.
`pick_chat` honours the user's preference and falls back to a hardcoded
order. `pick_tts` is OpenRouter-or-nothing (frontend handles the browser
fallback). `pick_stt` is OpenRouter-only — STT lives there permanently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.provider_settings.models import ProviderSettings
from app.provider_settings.schema import ChatProvider


class NoProviderConfiguredError(RuntimeError):
    """Raised when a capability is requested but no provider supports it."""


@dataclass(frozen=True)
class ChatPick:
    provider: ChatProvider
    model_name: str
    # Provider-specific creds. Only the field for `provider` is set.
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    zai_api_key: str | None = None
    zai_endpoint: str | None = None
    codex_auth_json: str | None = None


@dataclass(frozen=True)
class TTSPick:
    api_key: str  # OpenRouter is the only TTS provider for now
    model_name: str | None = None
    voice: str | None = None


@dataclass(frozen=True)
class STTPick:
    api_key: str  # OpenRouter only


_PREFERENCE_ORDER: tuple[ChatProvider, ...] = (
    "openai",
    "openrouter",
    "zai",
    "codex",
)
SUPPORTED_CHAT_PROVIDERS = frozenset(_PREFERENCE_ORDER)
_DEFAULT_CHAT_MODELS: dict[ChatProvider, str] = {
    "openai": "gpt-5.1",
    "openrouter": "openrouter/auto",
    "zai": "glm-5.1",
    "codex": "gpt-5-codex",
}


def _get_singleton(db: Session) -> ProviderSettings:
    """Fetch the id=1 row, creating it on first read."""
    row = db.get(ProviderSettings, 1)
    if row is None:
        row = ProviderSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_settings(db: Session) -> ProviderSettings:
    return _get_singleton(db)


def _configured_chat_providers(row: ProviderSettings) -> set[ChatProvider]:
    out: set[ChatProvider] = set()
    if row.openai_api_key:
        out.add("openai")
    if row.openrouter_api_key:
        out.add("openrouter")
    if row.zai_api_key:
        out.add("zai")
    if row.codex_auth_json:
        out.add("codex")
    return out


def _model_for(row: ProviderSettings, provider: ChatProvider) -> str:
    user_model: str | None
    if provider == "openai":
        user_model = row.openai_chat_model
    elif provider == "openrouter":
        user_model = row.openrouter_chat_model
    elif provider == "zai":
        user_model = row.zai_chat_model
    else:
        user_model = row.codex_chat_model
    return user_model or _DEFAULT_CHAT_MODELS[provider]


def _build_chat_pick(row: ProviderSettings, provider: ChatProvider) -> ChatPick:
    model_name = _model_for(row, provider)
    if provider == "openai":
        assert row.openai_api_key is not None
        return ChatPick(provider="openai", model_name=model_name, openai_api_key=row.openai_api_key)
    if provider == "openrouter":
        assert row.openrouter_api_key is not None
        return ChatPick(
            provider="openrouter",
            model_name=model_name,
            openrouter_api_key=row.openrouter_api_key,
        )
    if provider == "zai":
        assert row.zai_api_key is not None
        return ChatPick(
            provider="zai",
            model_name=model_name,
            zai_api_key=row.zai_api_key,
            zai_endpoint=row.zai_endpoint,
        )
    if provider == "codex":
        assert row.codex_auth_json is not None
        return ChatPick(
            provider="codex",
            model_name=model_name,
            codex_auth_json=row.codex_auth_json,
        )
    raise RuntimeError(f"Unsupported chat provider: {provider}")


def pick_chat(db: Session) -> ChatPick:
    row = _get_singleton(db)
    configured = _configured_chat_providers(row)
    if not configured:
        raise NoProviderConfiguredError(
            "No chat provider is configured. Add an API key in Settings before chatting."
        )

    preferred = row.preferred_chat_provider
    if preferred is not None and preferred in configured:
        return _build_chat_pick(row, cast(ChatProvider, preferred))

    for candidate in _PREFERENCE_ORDER:
        if candidate in configured:
            return _build_chat_pick(row, candidate)

    raise NoProviderConfiguredError("No chat provider is configured.")


def pick_tts(db: Session) -> TTSPick | None:
    """Return None if no provider can synthesise speech — frontend falls
    back to the browser's `speechSynthesis`."""
    row = _get_singleton(db)
    if row.openrouter_api_key:
        return TTSPick(
            api_key=row.openrouter_api_key,
            model_name=row.openrouter_tts_model,
            voice=row.openrouter_tts_voice,
        )
    return None


def pick_stt(db: Session) -> STTPick:
    """STT always routes through OpenRouter (Whisper). Required."""
    row = _get_singleton(db)
    if not row.openrouter_api_key:
        raise NoProviderConfiguredError(
            "Speech-to-text needs an OpenRouter API key. Add one in Settings."
        )
    return STTPick(api_key=row.openrouter_api_key)


def is_chat_configured() -> bool:
    """Cheap check used by onboarding-state code paths.

    Conservative on uncertainty: missing table → False (e.g. a unit test
    that never ran migrations)."""
    try:
        with SessionLocal() as db:
            row = db.get(ProviderSettings, 1)
            if row is None:
                return False
            return bool(_configured_chat_providers(row))
    except OperationalError:
        return False


# -------- mutations --------


def _apply_partial(target: ProviderSettings, updates: dict[str, Any]) -> None:
    """Set attrs from updates, treating explicit empty strings as 'clear'.

    A None value means "leave existing alone" — lets the UI PATCH the
    chat_model without forcing a re-paste of the API key, and vice versa.
    """
    for field, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            setattr(target, field, None)
        else:
            setattr(target, field, value)


def update_openai(db: Session, *, api_key: str | None, chat_model: str | None) -> ProviderSettings:
    row = _get_singleton(db)
    _apply_partial(row, {"openai_api_key": api_key, "openai_chat_model": chat_model})
    db.commit()
    db.refresh(row)
    _invalidate_agent()
    return row


def update_openrouter(
    db: Session,
    *,
    api_key: str | None,
    chat_model: str | None,
    tts_model: str | None = None,
    tts_voice: str | None = None,
) -> ProviderSettings:
    row = _get_singleton(db)
    _apply_partial(
        row,
        {
            "openrouter_api_key": api_key,
            "openrouter_chat_model": chat_model,
            "openrouter_tts_model": tts_model,
            "openrouter_tts_voice": tts_voice,
        },
    )
    db.commit()
    db.refresh(row)
    _invalidate_agent()
    return row


def update_zai(
    db: Session,
    *,
    api_key: str | None,
    endpoint: str | None,
    chat_model: str | None,
) -> ProviderSettings:
    row = _get_singleton(db)
    _apply_partial(
        row,
        {
            "zai_api_key": api_key,
            "zai_endpoint": endpoint,
            "zai_chat_model": chat_model,
        },
    )
    db.commit()
    db.refresh(row)
    _invalidate_agent()
    return row


def update_codex(db: Session, *, auth_json: str | None, chat_model: str | None) -> ProviderSettings:
    row = _get_singleton(db)
    _apply_partial(row, {"codex_auth_json": auth_json, "codex_chat_model": chat_model})
    db.commit()
    db.refresh(row)
    _invalidate_agent()
    return row


def update_preferred_chat(db: Session, *, preferred: ChatProvider | None) -> ProviderSettings:
    row = _get_singleton(db)
    row.preferred_chat_provider = preferred
    db.commit()
    db.refresh(row)
    _invalidate_agent()
    return row


async def persist_codex_auth(blob: str) -> None:
    """Write a refreshed Codex auth.json blob back to the singleton row.

    Called from inside the Codex provider's httpx auth flow after a
    token refresh. Deliberately does NOT call `_invalidate_agent` — the
    agent is mid-request when this fires, and the next request reads
    the same column anyway.
    """
    with SessionLocal() as db:
        row = db.get(ProviderSettings, 1)
        if row is None:
            return
        row.codex_auth_json = blob
        db.commit()


def _invalidate_agent() -> None:
    """Drop the cached agent so the next request rebuilds with new creds."""
    from app import agent as agent_module

    agent_module.invalidate_agent()
