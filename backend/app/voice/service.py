"""Voice (TTS + STT) dispatch.

STT always routes to OpenRouter (Whisper via `/audio/transcriptions`).
TTS uses OpenRouter when its API key is configured; otherwise the
endpoint returns 501 and the frontend falls back to the browser's
`speechSynthesis`. Provider-per-capability lives in
`app.provider_settings.service`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db import SessionLocal
from app.provider_settings import service as provider_service
from app.voice.providers import openrouter as openrouter_provider


class VoiceConfigError(Exception):
    """No provider can serve the requested capability."""


class VoiceProviderError(Exception):
    """Underlying provider rejected the request or returned no payload."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    provider: str
    model: str


@dataclass(frozen=True)
class SpeechSynthesisResult:
    audio: bytes
    content_type: str
    provider: str
    model: str


# Hard cap on synthesis input — server-side TTS is paid per character
# and the user can always chunk longer text client-side if they really
# want to play a wall of prose.
MAX_SYNTHESIS_CHARS = 4000


async def transcribe_audio(*, audio: bytes, content_type: str | None) -> TranscriptionResult:
    """Run the audio through OpenRouter's Whisper endpoint.

    Raises:
        VoiceConfigError: OpenRouter isn't configured.
        VoiceProviderError: HTTP failure or empty transcript.
    """
    if not audio:
        raise VoiceProviderError("Audio payload is empty.")

    with SessionLocal() as db:
        try:
            pick = provider_service.pick_stt(db)
        except provider_service.NoProviderConfiguredError as exc:
            raise VoiceConfigError(str(exc)) from exc

    text, model = await openrouter_provider.transcribe(
        api_key=pick.api_key,
        audio=audio,
        content_type=content_type,
    )
    return TranscriptionResult(text=text, provider="openrouter", model=model)


async def synthesize_speech(*, text: str) -> SpeechSynthesisResult:
    """Synthesize via OpenRouter when configured; otherwise raise so the
    frontend can fall back to the browser's `speechSynthesis`.

    Raises:
        VoiceConfigError: No TTS provider configured (frontend → browser).
        VoiceProviderError: Provider HTTP failure or empty audio.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise VoiceProviderError("Text payload is empty.")
    if len(cleaned) > MAX_SYNTHESIS_CHARS:
        raise VoiceProviderError(
            f"Text is too long for synthesis (max {MAX_SYNTHESIS_CHARS} characters)."
        )

    with SessionLocal() as db:
        pick = provider_service.pick_tts(db)
    if pick is None:
        raise VoiceConfigError(
            "No TTS provider configured — add an OpenRouter API key in Settings to enable server-side speech."
        )

    audio, content_type, model = await openrouter_provider.synthesize(
        api_key=pick.api_key,
        text=cleaned,
        model=pick.model_name,
        voice=pick.voice,
    )
    return SpeechSynthesisResult(
        audio=audio,
        content_type=content_type,
        provider="openrouter",
        model=model,
    )
