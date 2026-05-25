"""Pydantic schemas for the multi-provider settings endpoint.

Each provider has its own typed in/out pair. The aggregate `GET`
returns one block per provider with a `configured` flag and the
model/endpoint the UI needs to display; raw secrets never go out.
PATCH endpoints accept partial updates per provider.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ChatProvider = Literal["openai", "openrouter", "zai", "codex"]


def _validate_single_line_api_key(value: str | None) -> str | None:
    """Reject API keys containing whitespace or control chars.

    These tokens are always single-line opaque strings. Pasting a
    multi-line value (e.g. the Codex auth.json blob) into the OpenRouter
    key field would otherwise be stored verbatim and then handed to
    httpx as an `Authorization: Bearer …` header, where it both fails
    and surfaces the raw secret in the resulting `LocalProtocolError`
    message — see issue #129.
    """
    if value is None:
        return None
    if value == "":
        return ""  # Sentinel: "clear the stored value".
    stripped = value.strip()
    if any(ch.isspace() for ch in stripped) or any(ord(ch) < 0x20 for ch in stripped):
        raise ValueError(
            "API key must be a single-line token without whitespace or control characters."
        )
    return stripped


class OpenAIIn(BaseModel):
    api_key: str | None = None  # None = leave existing key untouched
    chat_model: str | None = Field(default=None, max_length=128)

    _normalise_api_key = field_validator("api_key")(_validate_single_line_api_key)


class OpenAIOut(BaseModel):
    configured: bool
    chat_model: str | None


class OpenRouterIn(BaseModel):
    api_key: str | None = None
    chat_model: str | None = Field(default=None, max_length=128)
    tts_model: str | None = Field(default=None, max_length=255)
    tts_voice: str | None = Field(default=None, max_length=128)

    _normalise_api_key = field_validator("api_key")(_validate_single_line_api_key)


class OpenRouterOut(BaseModel):
    configured: bool
    chat_model: str | None
    tts_model: str | None
    tts_voice: str | None


class ZAIIn(BaseModel):
    api_key: str | None = None
    endpoint: str | None = Field(default=None, max_length=255)
    chat_model: str | None = Field(default=None, max_length=128)

    _normalise_api_key = field_validator("api_key")(_validate_single_line_api_key)


class ZAIOut(BaseModel):
    configured: bool
    endpoint: str | None
    chat_model: str | None


class CodexIn(BaseModel):
    auth_json: str | None = None
    chat_model: str | None = Field(default=None, max_length=128)


class CodexOut(BaseModel):
    configured: bool
    chat_model: str | None


class PreferredChatIn(BaseModel):
    preferred_chat_provider: ChatProvider | None


class ProviderSettingsOut(BaseModel):
    preferred_chat_provider: ChatProvider | None
    openai: OpenAIOut
    openrouter: OpenRouterOut
    zai: ZAIOut
    codex: CodexOut
