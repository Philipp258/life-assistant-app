"""Read/write the DB-backed runtime settings table.

Keys are whitelisted in ``SUPPORTED_RUNTIME_SETTINGS`` — the table is
deliberately not a generic kv store, because most env-backed config
(SESSION_SECRET, DATABASE_URL, …) is needed before the DB is reachable.
"""

from __future__ import annotations

import math

from sqlalchemy.orm import Session

from app.settings.models import AppSetting

SUPPORTED_RUNTIME_SETTINGS: tuple[str, ...] = (
    "brave_api_key",
    "vad_timeout_ms",
    "voice_playback_speed",
    "assistant_name",
    "user_name",
)
DEFAULT_VAD_TIMEOUT_MS = 4_000
MIN_VAD_TIMEOUT_MS = 250
MAX_VAD_TIMEOUT_MS = 30_000
DEFAULT_VOICE_PLAYBACK_SPEED = 1.15
MIN_VOICE_PLAYBACK_SPEED = 0.5
MAX_VOICE_PLAYBACK_SPEED = 2.0
IDENTITY_NAME_KEYS: tuple[str, ...] = ("assistant_name", "user_name")
MAX_IDENTITY_NAME_LEN = 64


def _validate_key(key: str) -> None:
    if key not in SUPPORTED_RUNTIME_SETTINGS:
        raise ValueError(
            f"Unsupported runtime setting {key!r}; expected one of {SUPPORTED_RUNTIME_SETTINGS}."
        )


def _validate_value(key: str, value: str) -> str:
    if key in IDENTITY_NAME_KEYS:
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{key} must be non-empty.")
        if len(stripped) > MAX_IDENTITY_NAME_LEN:
            raise ValueError(f"{key} must be at most {MAX_IDENTITY_NAME_LEN} characters.")
        return stripped
    if value == "":
        return value
    if key == "vad_timeout_ms":
        try:
            timeout_ms = int(value)
        except ValueError as exc:
            raise ValueError("vad_timeout_ms must be an integer number of milliseconds.") from exc
        if not MIN_VAD_TIMEOUT_MS <= timeout_ms <= MAX_VAD_TIMEOUT_MS:
            raise ValueError(
                "vad_timeout_ms must be between "
                f"{MIN_VAD_TIMEOUT_MS} and {MAX_VAD_TIMEOUT_MS} milliseconds."
            )
        return str(timeout_ms)
    if key == "voice_playback_speed":
        try:
            speed = float(value)
        except ValueError as exc:
            raise ValueError("voice_playback_speed must be a number.") from exc
        if not math.isfinite(speed):
            raise ValueError("voice_playback_speed must be a finite number.")
        if not MIN_VOICE_PLAYBACK_SPEED <= speed <= MAX_VOICE_PLAYBACK_SPEED:
            raise ValueError(
                "voice_playback_speed must be between "
                f"{MIN_VOICE_PLAYBACK_SPEED:g} and {MAX_VOICE_PLAYBACK_SPEED:g}."
            )
        return f"{speed:g}"
    return value


def get_runtime_setting(db: Session, key: str) -> str | None:
    """Return the raw stored value, or None if there is no row."""
    _validate_key(key)
    row = db.get(AppSetting, key)
    if row is None:
        return None
    return row.value


def set_runtime_setting(db: Session, *, key: str, value: str) -> str:
    """Upsert a runtime setting. Empty string is a valid value (clears it)."""
    _validate_key(key)
    value = _validate_value(key, value)
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    db.refresh(row)
    return row.value


def list_runtime_settings(db: Session) -> dict[str, str]:
    """Return every supported setting, defaulting unset rows to ``""``.

    Always includes every key in ``SUPPORTED_RUNTIME_SETTINGS`` so the
    UI can render a stable form without round-trip per field.
    """
    values: dict[str, str] = {}
    for key in SUPPORTED_RUNTIME_SETTINGS:
        row = db.get(AppSetting, key)
        values[key] = row.value if row is not None else ""
    return values


def get_brave_api_key(db: Session) -> str | None:
    """Return the configured Brave Search API key, or None if blank/unset.

    Whitespace-only values are treated as unset so the UI can clear the
    field with a single save instead of needing a separate delete path.
    """
    value = get_runtime_setting(db, "brave_api_key")
    if value is None or not value.strip():
        return None
    return value
