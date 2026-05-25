"""OpenRouter ASR + TTS adapter.

OpenRouter's `/audio/transcriptions` endpoint takes a JSON body with a
base64-encoded `input_audio` blob — *not* OpenAI-style multipart.
`/audio/speech` mirrors OpenAI: JSON in, binary out.

Model and voice defaults can be overridden from provider settings.
"""

from __future__ import annotations

import base64
import logging

import httpx

from app.agent.providers.openrouter import OPENROUTER_BASE_URL
from app.redaction import redact_bearer
from app.voice.providers._common import (
    OPENAI_AUDIO_FORMATS,
    audio_format_for_input,
    sanitize_provider_error,
)

log = logging.getLogger(__name__)

DEFAULT_ASR_MODEL = "openai/whisper-1"
DEFAULT_TTS_MODEL = "canopylabs/orpheus-3b-0.1-ft"
DEFAULT_TTS_VOICE = "tara"
DEFAULT_TTS_FORMAT = "mp3"

# Map OpenAI's `response_format` values to MIME so the frontend's <audio>
# element picks a matching decoder.
TTS_RESPONSE_MIME = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "pcm": "audio/L16",
}


async def transcribe(
    *,
    api_key: str,
    audio: bytes,
    content_type: str | None,
) -> tuple[str, str]:
    """Return `(transcript, model_name)`.

    Raises:
        VoiceProviderError: HTTP failure or empty transcript.
    """
    from app.voice.service import VoiceProviderError

    model = DEFAULT_ASR_MODEL
    fmt = audio_format_for_input(content_type, allowed=OPENAI_AUDIO_FORMATS, default="webm")
    encoded = base64.b64encode(audio).decode("ascii")

    payload = {"model": model, "input_audio": {"data": encoded, "format": fmt}}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    url = f"{OPENROUTER_BASE_URL}/audio/transcriptions"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        # httpx.LocalProtocolError quotes the offending header — redact
        # any `Bearer …` payload before the message reaches the log.
        log.warning("OpenRouter transcription request failed: %s", redact_bearer(str(exc)))
        raise VoiceProviderError("OpenRouter transcription request failed.") from exc

    if response.status_code >= 400:
        raise VoiceProviderError(
            sanitize_provider_error(
                "OpenRouter",
                status_code=response.status_code,
                body=response.text,
            )
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise VoiceProviderError("OpenRouter returned a non-JSON response.") from exc

    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise VoiceProviderError("OpenRouter returned an empty transcript.")

    return text.strip(), model


async def synthesize(
    *, api_key: str, text: str, model: str | None = None, voice: str | None = None
) -> tuple[bytes, str, str]:
    """Return `(audio_bytes, content_type, model_name)`."""
    from app.voice.service import VoiceProviderError

    model = (model or DEFAULT_TTS_MODEL).strip() or DEFAULT_TTS_MODEL
    voice = (voice or DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE
    content_type = TTS_RESPONSE_MIME[DEFAULT_TTS_FORMAT]

    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": DEFAULT_TTS_FORMAT,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    url = f"{OPENROUTER_BASE_URL}/audio/speech"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("OpenRouter speech request failed: %s", redact_bearer(str(exc)))
        raise VoiceProviderError("OpenRouter speech request failed.") from exc

    if response.status_code >= 400:
        raise VoiceProviderError(
            sanitize_provider_error(
                "OpenRouter",
                status_code=response.status_code,
                body=response.text,
                action="speech synthesis",
            )
        )

    audio = response.content
    if not audio:
        raise VoiceProviderError("OpenRouter returned an empty audio payload.")

    return audio, content_type, model
