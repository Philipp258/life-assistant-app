"""Shared helpers for voice provider adapters."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# OpenAI's input_audio content type accepts a small set of format hints.
# Anything outside this list is silently coerced to ``default``.
OPENAI_AUDIO_FORMATS = frozenset({"wav", "mp3", "webm", "ogg", "flac", "m4a", "mp4"})

# Concise, user-safe summaries of common HTTP failure modes. The raw
# upstream body is logged server-side; the UI only ever sees one of these.
_STATUS_SUMMARIES = {
    400: "bad request",
    401: "authentication failed — reconnect or refresh credentials",
    403: "authentication/permission error — reconnect or refresh credentials",
    404: "endpoint not found",
    408: "upstream timed out",
    413: "payload too large for the provider",
    415: "format not supported by the provider",
    422: "rejected by the provider",
    429: "rate limited — try again shortly",
    500: "upstream service error",
    502: "upstream service error",
    503: "upstream service unavailable",
    504: "upstream service timed out",
}


def sanitize_provider_error(
    provider_label: str,
    *,
    status_code: int,
    body: str,
    headers: Any = None,
    action: str = "transcription",
) -> str:
    """Return a concise, UI-safe error string for an upstream HTTP failure.

    The raw body (which may contain Cloudflare HTML, stack traces, or
    other noise) is logged at WARNING level with truncation; the returned
    string never includes that body, only a short summary keyed off the
    status code.
    """
    truncated = (body or "")[:500].replace("\n", " ").strip()
    log.warning(
        "voice provider error provider=%s action=%s status=%s body=%r",
        provider_label,
        action,
        status_code,
        truncated,
    )
    summary = _STATUS_SUMMARIES.get(status_code)
    if summary:
        return f"{provider_label} {action} failed: {summary} ({status_code})."
    return f"{provider_label} {action} failed ({status_code})."


# Map well-known MIME types to OpenAI-style format hints.
_MIME_TO_FORMAT = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
}


def audio_format_for_input(
    content_type: str | None,
    *,
    allowed: frozenset[str] = OPENAI_AUDIO_FORMATS,
    default: str = "webm",
) -> str:
    """Best-effort mapping from a multipart ``content_type`` to a format hint."""
    if not content_type:
        return default
    primary = content_type.split(";", 1)[0].strip().lower()
    fmt = _MIME_TO_FORMAT.get(primary)
    if fmt and fmt in allowed:
        return fmt
    # Fallback: take the subtype (audio/<x>) and accept it if it matches.
    if "/" in primary:
        sub = primary.split("/", 1)[1]
        if sub in allowed:
            return sub
    return default


def extract_openai_text(payload: Any) -> str:
    """Pull the text out of an OpenAI-style chat completion response."""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    # Some providers return a list of content parts.
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
            elif isinstance(part, str):
                chunks.append(part)
        return "".join(chunks).strip()
    return ""
