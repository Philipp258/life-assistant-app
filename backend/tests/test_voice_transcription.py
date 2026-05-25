"""Tests for /api/voice/transcribe + /api/voice/synthesize.

STT always routes through OpenRouter (Whisper). TTS uses OpenRouter when
configured and returns 501 otherwise so the frontend falls back to the
browser's `speechSynthesis`.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.voice import service as voice_service


# ── Helpers ──────────────────────────────────────────────────────


def _set_openrouter_key(
    db_session: Session,
    api_key: str,
    *,
    tts_model: str | None = None,
    tts_voice: str | None = None,
) -> None:
    """Configure only an OpenRouter API key on the singleton settings row."""
    from app.provider_settings import service

    service.update_openrouter(
        db_session,
        api_key=api_key,
        chat_model=None,
        tts_model=tts_model,
        tts_voice=tts_voice,
    )


def _clear_openrouter_key(db_session: Session) -> None:
    from app.provider_settings import service

    service.update_openrouter(db_session, api_key="", chat_model=None)


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in that records the last request."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.last_url: str | None = None
        self.last_json: Any = None
        self.last_headers: dict[str, str] | None = None

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> httpx.Response:
        self.last_url = url
        self.last_json = json
        self.last_headers = headers
        return self.response


def _transcription_response(text: str) -> httpx.Response:
    return httpx.Response(200, json={"text": text}, request=httpx.Request("POST", "http://x"))


def _binary_response(audio: bytes, content_type: str = "audio/mpeg") -> httpx.Response:
    return httpx.Response(
        200,
        content=audio,
        headers={"content-type": content_type},
        request=httpx.Request("POST", "http://x"),
    )


# ── Endpoint-level dispatch ──────────────────────────────────────


def test_voice_transcribe_requires_openrouter(client: TestClient, db_session: Session) -> None:
    _clear_openrouter_key(db_session)

    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", b"audio", "audio/webm")},
    )
    assert response.status_code == 400, response.text
    assert "openrouter" in response.json()["detail"].lower()


def test_voice_transcribe_rejects_empty_audio(client: TestClient) -> None:
    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", b"", "audio/webm")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_voice_transcribe_requires_auth(unauthed_client: TestClient) -> None:
    response = unauthed_client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", b"audio", "audio/webm")},
    )
    assert response.status_code == 401


# ── OpenRouter transcribe adapter ────────────────────────────────


def test_openrouter_transcription_round_trip(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_openrouter_key(db_session, "sk-or-test")

    fake = _FakeAsyncClient(_transcription_response("hello world"))
    monkeypatch.setattr("app.voice.providers.openrouter.httpx.AsyncClient", lambda **_: fake)

    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", b"audio-bytes", "audio/webm")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "text": "hello world",
        "provider": "openrouter",
        "model": "openai/whisper-1",
    }

    assert fake.last_url == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert fake.last_headers["Authorization"] == "Bearer sk-or-test"
    assert fake.last_json["model"] == "openai/whisper-1"
    audio = fake.last_json["input_audio"]
    assert audio["format"] == "webm"
    assert base64.b64decode(audio["data"]) == b"audio-bytes"


def test_openrouter_provider_http_failure(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_openrouter_key(db_session, "sk-or-test")

    fake = _FakeAsyncClient(
        httpx.Response(503, text="upstream down", request=httpx.Request("POST", "http://x"))
    )
    monkeypatch.setattr("app.voice.providers.openrouter.httpx.AsyncClient", lambda **_: fake)

    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", b"audio", "audio/webm")},
    )
    assert response.status_code == 502
    assert "openrouter" in response.json()["detail"].lower()


def test_openrouter_empty_transcript_is_502(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_openrouter_key(db_session, "sk-or-test")

    fake = _FakeAsyncClient(_transcription_response("   "))
    monkeypatch.setattr("app.voice.providers.openrouter.httpx.AsyncClient", lambda **_: fake)

    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", b"audio", "audio/webm")},
    )
    assert response.status_code == 502
    assert "empty" in response.json()["detail"].lower()


def test_openrouter_transport_failure_does_not_leak_bearer(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A transport error that quotes the Authorization header (httpx's
    `LocalProtocolError` does this when the api_key contains forbidden
    chars) must not surface the bearer payload in the log. See #129."""
    import asyncio
    import logging

    from app.voice.providers import openrouter

    class _ExplodingClient:
        async def __aenter__(self) -> "_ExplodingClient":
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> object:
            raise httpx.LocalProtocolError(
                'Illegal header value b\'Bearer {\\n  "auth_mode": "chatgpt", '
                '"tokens": {"access_token": "eyJleAk", '
                '"refresh_token": "rt-leaked-xyz"}}\''
            )

    monkeypatch.setattr(
        "app.voice.providers.openrouter.httpx.AsyncClient", lambda **_: _ExplodingClient()
    )

    from app.voice.service import VoiceProviderError

    with caplog.at_level(logging.WARNING, logger="app.voice.providers.openrouter"):
        with pytest.raises(VoiceProviderError):
            asyncio.run(
                openrouter.transcribe(
                    api_key="ignored",
                    audio=b"audio",
                    content_type="audio/webm",
                )
            )

    log_text = " ".join(record.getMessage() for record in caplog.records)
    assert "Bearer ***" in log_text
    assert "rt-leaked-xyz" not in log_text
    assert "access_token" not in log_text
    assert "auth_mode" not in log_text


def test_openrouter_500_body_is_sanitized(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_openrouter_key(db_session, "sk-or-test")

    fake = _FakeAsyncClient(
        httpx.Response(
            500,
            text="<html><body>Internal Server Error: stack trace ...</body></html>",
            request=httpx.Request("POST", "http://x"),
        )
    )
    monkeypatch.setattr("app.voice.providers.openrouter.httpx.AsyncClient", lambda **_: fake)

    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", b"audio", "audio/webm")},
    )
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "<" not in detail
    assert "stack trace" not in detail.lower()
    assert "openrouter" in detail.lower()
    assert "500" in detail


# ── Sanitizer helper ─────────────────────────────────────────────


def test_sanitize_provider_error_strips_html_body(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from app.voice.providers._common import sanitize_provider_error

    html = "<html><body>tag soup with <script>alert(1)</script></body></html>"
    with caplog.at_level(logging.WARNING, logger="app.voice.providers._common"):
        msg = sanitize_provider_error("OpenRouter", status_code=403, body=html)
    assert "<" not in msg
    assert "alert(1)" not in msg
    assert "tag soup" not in msg
    assert msg.startswith("OpenRouter transcription failed")
    assert "(403)" in msg
    log_text = " ".join(record.getMessage() for record in caplog.records)
    assert "tag soup" in log_text


def test_sanitize_provider_error_unknown_status_falls_back() -> None:
    from app.voice.providers._common import sanitize_provider_error

    msg = sanitize_provider_error("OpenRouter", status_code=418, body="teapot")
    assert msg == "OpenRouter transcription failed (418)."
    assert "teapot" not in msg


@pytest.mark.parametrize(
    ("status_code", "needle"),
    [
        (401, "authentication"),
        (403, "credentials"),
        (429, "rate limited"),
        (503, "unavailable"),
    ],
)
def test_sanitize_provider_error_status_messages(status_code: int, needle: str) -> None:
    from app.voice.providers._common import sanitize_provider_error

    msg = sanitize_provider_error("OpenRouter", status_code=status_code, body="x" * 1000)
    assert needle in msg.lower()
    assert f"({status_code})" in msg


# ── Service-level direct call (non-HTTP) ─────────────────────────


def test_dispatch_raises_voice_config_error_when_unconfigured(
    db_session: Session,
) -> None:
    """Service-level call (not through HTTP) raises a typed error."""
    import asyncio

    _clear_openrouter_key(db_session)

    with pytest.raises(voice_service.VoiceConfigError):
        asyncio.run(voice_service.transcribe_audio(audio=b"audio", content_type="audio/webm"))


def test_dispatch_rejects_empty_audio() -> None:
    import asyncio

    with pytest.raises(voice_service.VoiceProviderError):
        asyncio.run(voice_service.transcribe_audio(audio=b"", content_type="audio/webm"))


# ── Format inference helper ──────────────────────────────────────


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("audio/webm", "webm"),
        ("audio/webm;codecs=opus", "webm"),
        ("audio/mp4", "mp4"),
        ("audio/x-m4a", "m4a"),
        ("audio/mpeg", "mp3"),
        ("audio/wav", "wav"),
        (None, "webm"),
        ("application/octet-stream", "webm"),
    ],
)
def test_audio_format_for_input(content_type: str | None, expected: str) -> None:
    from app.voice.providers._common import audio_format_for_input

    assert audio_format_for_input(content_type) == expected


# ── /voice/synthesize endpoint ───────────────────────────────────


def test_voice_synthesize_returns_501_when_unconfigured(
    client: TestClient, db_session: Session
) -> None:
    _clear_openrouter_key(db_session)

    response = client.post("/api/voice/synthesize", json={"text": "hello"})
    # 501 lets the frontend fall back to browser TTS.
    assert response.status_code == 501, response.text
    assert "openrouter" in response.json()["detail"].lower()


def test_voice_synthesize_rejects_empty_text(client: TestClient) -> None:
    response = client.post("/api/voice/synthesize", json={"text": ""})
    # Pydantic min_length=1 validation kicks in before service-level checks.
    assert response.status_code == 422


def test_voice_synthesize_rejects_oversize_text(client: TestClient, db_session: Session) -> None:
    _set_openrouter_key(db_session, "sk-or-test")
    huge = "a" * (voice_service.MAX_SYNTHESIS_CHARS + 1)
    response = client.post("/api/voice/synthesize", json={"text": huge})
    assert response.status_code == 502
    assert "too long" in response.json()["detail"].lower()


def test_voice_synthesize_requires_auth(unauthed_client: TestClient) -> None:
    response = unauthed_client.post("/api/voice/synthesize", json={"text": "hello"})
    assert response.status_code == 401


def test_openrouter_synthesize_round_trip(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_openrouter_key(db_session, "sk-or-test")

    fake = _FakeAsyncClient(_binary_response(b"\x00\x01mp3-bytes"))
    monkeypatch.setattr("app.voice.providers.openrouter.httpx.AsyncClient", lambda **_: fake)

    response = client.post("/api/voice/synthesize", json={"text": "hello world"})
    assert response.status_code == 200, response.text
    assert response.content == b"\x00\x01mp3-bytes"
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["x-voice-provider"] == "openrouter"
    assert response.headers["x-voice-model"] == "canopylabs/orpheus-3b-0.1-ft"

    assert fake.last_url == "https://openrouter.ai/api/v1/audio/speech"
    assert fake.last_headers["Authorization"] == "Bearer sk-or-test"
    assert fake.last_json == {
        "model": "canopylabs/orpheus-3b-0.1-ft",
        "input": "hello world",
        "voice": "tara",
        "response_format": "mp3",
    }


def test_openrouter_synthesize_uses_configured_tts_model(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_openrouter_key(db_session, "sk-or-test", tts_model="hexgrad/kokoro-82m")

    fake = _FakeAsyncClient(_binary_response(b"mp3-bytes"))
    monkeypatch.setattr("app.voice.providers.openrouter.httpx.AsyncClient", lambda **_: fake)

    response = client.post("/api/voice/synthesize", json={"text": "hello"})
    assert response.status_code == 200, response.text
    assert response.headers["x-voice-model"] == "hexgrad/kokoro-82m"
    assert fake.last_json["model"] == "hexgrad/kokoro-82m"


def test_openrouter_synthesize_uses_configured_tts_voice(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_openrouter_key(db_session, "sk-or-test", tts_voice="leah")

    fake = _FakeAsyncClient(_binary_response(b"mp3-bytes"))
    monkeypatch.setattr("app.voice.providers.openrouter.httpx.AsyncClient", lambda **_: fake)

    response = client.post("/api/voice/synthesize", json={"text": "hello"})
    assert response.status_code == 200, response.text
    assert fake.last_json["voice"] == "leah"


def test_openrouter_synthesize_empty_tts_voice_falls_back_to_tara(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app.voice.providers import openrouter

    fake = _FakeAsyncClient(_binary_response(b"mp3-bytes"))
    monkeypatch.setattr("app.voice.providers.openrouter.httpx.AsyncClient", lambda **_: fake)

    asyncio.run(openrouter.synthesize(api_key="sk-or-test", text="hello", voice="   "))
    assert fake.last_json["voice"] == "tara"


def test_openrouter_synthesize_provider_error_is_502(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_openrouter_key(db_session, "sk-or-test")

    fake = _FakeAsyncClient(
        httpx.Response(429, text="rate limited", request=httpx.Request("POST", "http://x"))
    )
    monkeypatch.setattr("app.voice.providers.openrouter.httpx.AsyncClient", lambda **_: fake)

    response = client.post("/api/voice/synthesize", json={"text": "hi"})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "openrouter" in detail.lower()
    assert "speech synthesis" in detail.lower()
    assert "429" in detail


def test_openrouter_synthesize_empty_audio_is_502(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_openrouter_key(db_session, "sk-or-test")

    fake = _FakeAsyncClient(_binary_response(b""))
    monkeypatch.setattr("app.voice.providers.openrouter.httpx.AsyncClient", lambda **_: fake)

    response = client.post("/api/voice/synthesize", json={"text": "hi"})
    assert response.status_code == 502
    assert "empty" in response.json()["detail"].lower()


def test_synthesize_dispatch_rejects_empty_text() -> None:
    import asyncio

    with pytest.raises(voice_service.VoiceProviderError):
        asyncio.run(voice_service.synthesize_speech(text="   "))
