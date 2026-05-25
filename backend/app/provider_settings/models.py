"""Singleton table holding creds for every chat/voice provider.

One row, id=1. Each provider gets its own typed columns; nulls mean
"not configured". The active chat provider is whichever name is in
`preferred_chat_provider` (and is itself configured). TTS and STT
routing is hardcoded in `service.pick_tts` / `pick_stt`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProviderSettings(Base):
    __tablename__ = "provider_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)

    # Which configured provider the chat agent should use. Null means
    # "auto" — service falls through a hardcoded preference order.
    preferred_chat_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # OpenAI (direct API)
    openai_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    openai_chat_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # OpenRouter
    openrouter_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    openrouter_chat_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    openrouter_tts_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    openrouter_tts_voice: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Z.ai
    zai_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    zai_endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    zai_chat_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Codex (ChatGPT subscription) — full auth.json blob, refreshed in place.
    codex_auth_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    codex_chat_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
