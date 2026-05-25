"""Centralized UTC datetime helpers.

The DB stores naive UTC datetimes (`DateTime` columns without
`timezone=True`). We always *treat* them as UTC, but every datetime that
crosses an API boundary must carry an explicit timezone marker (`Z`)
so browsers don't parse it as local time.

Use:
- `utc_now()` everywhere `datetime.utcnow()` was used (the latter is
  deprecated in Python 3.12+ and inconsistent under DST-shifting locales).
- `serialize_utc(dt)` for tool/JSON dict payloads built by hand.
- `UtcDatetime` as the field type in Pydantic schemas exposed via the
  HTTP API — its `PlainSerializer` emits a `Z`-suffixed string.
- `normalize_to_naive_utc(dt)` at write boundaries to coerce any inbound
  datetime (naive or timezone-aware) to the naive-UTC shape the DB
  columns expect.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, overload

from pydantic import PlainSerializer


def utc_now() -> datetime:
    """Current time as a naive UTC datetime.

    Drop-in replacement for the deprecated `datetime.utcnow()`. The DB
    columns are naive `DateTime`, so we strip the tzinfo after computing
    in UTC.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def ensure_aware_utc(dt: datetime | None) -> datetime | None:
    """Treat naive datetimes as UTC; convert aware datetimes to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def serialize_utc(dt: datetime | None) -> str | None:
    """Serialize a datetime as ISO-8601 with an explicit `Z` UTC marker.

    Naive datetimes are treated as UTC (the convention enforced by the
    `Task`/`Message`/etc. models). Aware datetimes are converted to UTC
    first so the suffix is always `Z`.
    """
    aware = ensure_aware_utc(dt)
    if aware is None:
        return None
    return aware.isoformat().replace("+00:00", "Z")


@overload
def normalize_to_naive_utc(dt: datetime) -> datetime: ...
@overload
def normalize_to_naive_utc(dt: None) -> None: ...
def normalize_to_naive_utc(dt: datetime | None) -> datetime | None:
    """Coerce any datetime to the naive-UTC shape the DB columns store.

    - `None` → `None`.
    - Naive datetime → assumed UTC, returned as-is.
    - Aware datetime → converted to UTC, tzinfo stripped.

    Used at API write boundaries (Pydantic input schemas) so a client
    sending `2026-05-07T21:25:00+02:00` ends up stored as the equivalent
    UTC instant rather than a wall-clock time tagged with a stale offset.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def _utc_json_serializer(value: datetime | None) -> str | None:
    return serialize_utc(value)


UtcDatetime = Annotated[
    datetime,
    PlainSerializer(_utc_json_serializer, return_type=str, when_used="json"),
]
"""Pydantic field type that serializes to a `Z`-suffixed UTC ISO string.

Validation behavior is unchanged from `datetime`: naive and aware
datetimes are both accepted on input. Use this for any datetime field
exposed via the HTTP API so frontend `new Date(iso)` parses as UTC and
renders in the browser's local timezone.
"""
