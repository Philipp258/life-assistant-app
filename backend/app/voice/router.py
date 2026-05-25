"""Voice transcription + synthesis endpoints.

Accepts a multipart upload (transcribe) or JSON text (synthesize),
dispatches to the configured provider, and returns either
``{ text, provider, model }`` or a binary audio response. Errors get
sane HTTP statuses so the frontend can show a useful message rather
than a generic 500.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from app.voice import service as voice_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

# 25 MB - Life Assistant records short utterances (a few seconds of webm/opus is
# tens of KB), so anything bigger is almost certainly a misuse and not
# worth shipping to a paid provider.
_MAX_AUDIO_BYTES = 25 * 1024 * 1024


class TranscribeResponse(BaseModel):
    text: str
    provider: str
    model: str


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(file: UploadFile = File(...)) -> TranscribeResponse:
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="Audio file is empty.")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio file too large (max {_MAX_AUDIO_BYTES // (1024 * 1024)} MB).",
        )

    try:
        result = await voice_service.transcribe_audio(
            audio=audio,
            content_type=file.content_type,
        )
    except voice_service.VoiceConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except voice_service.VoiceProviderError as exc:
        log.warning("voice transcription provider error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return TranscribeResponse(text=result.text, provider=result.provider, model=result.model)


@router.post("/synthesize")
async def synthesize(payload: SynthesizeRequest) -> Response:
    """Return raw audio bytes with the provider's content-type.

    Provider/model metadata is exposed via response headers so the
    frontend can log it without having to parse the (binary) body.
    A 501 means the configured provider doesn't support TTS yet — the
    frontend should fall back to the browser's ``speechSynthesis``.
    """
    try:
        result = await voice_service.synthesize_speech(text=payload.text)
    except voice_service.VoiceConfigError as exc:
        # Provider unconfigured or doesn't support TTS — 501 lets the
        # frontend distinguish "fall back to browser TTS" from real errors.
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except voice_service.VoiceProviderError as exc:
        log.warning("voice synthesis provider error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(
        content=result.audio,
        media_type=result.content_type,
        headers={
            "X-Voice-Provider": result.provider,
            "X-Voice-Model": result.model,
        },
    )
