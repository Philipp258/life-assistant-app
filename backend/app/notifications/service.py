"""Push notification fan-out.

Single chokepoint: sync event hooks call `schedule_notify(...)`, which
bridges to async `notify(...)` for the actual fan-out.
Iterates active `PushSubscription` rows, calls `pywebpush.webpush` per row
in a thread (the library is sync HTTP), drops 404/410 endpoints (the
push service has retired the subscription), and updates `last_seen_at`
on success.

VAPID keys come from settings. If any piece is missing we log once and
no-op every call — the rest of the app still boots so a fresh checkout
works without the push setup.

Suppression:
- `quiet_if_session_id` — skip when the user has that ChatSession's SSE
  stream open. Uses `app.chat.pubsub.subscriber_count`. The SSE-driven
  in-page UI already shows the new message; pushing again would buzz
  the same browser tab the user is staring at.
- `dedupe_key` — in-process TTL set (60s). Used for transient events
  like "errored 3x in a row" so a flapping run doesn't fire repeatedly.

Cross-process pubsub presence is out of scope (single-process app).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from collections.abc import Coroutine
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat import pubsub
from app.config import REPO_ROOT, settings
from app.datetime_utils import utc_now
from app.db import SessionLocal
from app.notifications.models import PushSubscription

logger = logging.getLogger(__name__)

_DEDUPE_TTL_SECONDS = 60.0
_dedupe: dict[str, float] = {}

_warned_no_vapid = False


def schedule(coro: Coroutine[Any, Any, None], *, label: str) -> None:
    """Run a best-effort notification coroutine from sync code.

    Push hooks live in synchronous services, while `notify(...)` is async.
    Keep the loop-bridging rules here so every caller gets the same behavior:
    use the currently running loop when one exists, otherwise dispatch onto
    the app's captured main loop, and close the coroutine if neither exists.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
        return
    except RuntimeError:
        pass

    from app.chat import runner as chat_runner

    main_loop = chat_runner._main_loop
    if main_loop is None or main_loop.is_closed():
        logger.debug("notifications: no main loop, dropping %s", label)
        coro.close()
        return
    asyncio.run_coroutine_threadsafe(coro, main_loop)


def schedule_notify(
    *,
    event_type: str,
    title: str,
    body: str,
    url: str,
    quiet_if_session_id: int | None = None,
    dedupe_key: str | None = None,
    tag: str | None = None,
) -> None:
    """Schedule `notify(...)` from a synchronous event hook."""
    schedule(
        notify(
            event_type=event_type,
            title=title,
            body=body,
            url=url,
            quiet_if_session_id=quiet_if_session_id,
            dedupe_key=dedupe_key,
            tag=tag,
        ),
        label=f"push notification {event_type}",
    )


def _vapid_ready() -> bool:
    global _warned_no_vapid
    ok = bool(
        settings.vapid_private_key_path
        and settings.vapid_public_key
        and settings.vapid_contact_email
    )
    if not ok and not _warned_no_vapid:
        logger.warning(
            "notifications: VAPID config missing — push fan-out disabled. "
            "Run `uv run python backend/scripts/gen_vapid_keys.py` and "
            "populate VAPID_PRIVATE_KEY_PATH / VAPID_PUBLIC_KEY / "
            "VAPID_CONTACT_EMAIL in .env."
        )
        _warned_no_vapid = True
    return ok


def _resolve_private_key_path() -> str | None:
    raw = settings.vapid_private_key_path
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return str(p)


def subscribe(
    db: Session,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None = None,
) -> PushSubscription:
    existing = db.scalars(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    ).first()
    if existing is not None:
        existing.p256dh = p256dh
        existing.auth = auth
        if user_agent is not None:
            existing.user_agent = user_agent
        existing.last_seen_at = utc_now()
        db.commit()
        db.refresh(existing)
        return existing
    row = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=user_agent)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def unsubscribe(db: Session, *, endpoint: str) -> bool:
    existing = db.scalars(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    ).first()
    if existing is None:
        return False
    db.delete(existing)
    db.commit()
    return True


def _check_dedupe(key: str | None) -> bool:
    """Return True if `key` was used within TTL (caller should skip)."""
    if not key:
        return False
    now = time.monotonic()
    expired = [k for k, t in _dedupe.items() if now - t > _DEDUPE_TTL_SECONDS]
    for k in expired:
        _dedupe.pop(k, None)
    if key in _dedupe:
        return True
    _dedupe[key] = now
    return False


def _send_one(subscription: PushSubscription, payload: dict[str, Any]) -> int | None:
    """Send one push. Returns HTTP status on transport failure, None on success.

    Hidden import so `pywebpush` is only required when push is actually
    configured. Tests patch this function directly to assert fan-out.
    """
    from pywebpush import WebPushException, webpush

    private_key = _resolve_private_key_path()
    if private_key is None:
        return None
    vapid_contact_email = settings.vapid_contact_email
    if vapid_contact_email is None:
        return None
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=private_key,
            vapid_claims={"sub": vapid_contact_email},
        )
        return None
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None) if exc.response else None
        return status if status is not None else 0


async def notify(
    *,
    event_type: str,
    title: str,
    body: str,
    url: str,
    quiet_if_session_id: int | None = None,
    dedupe_key: str | None = None,
    tag: str | None = None,
) -> None:
    """Fan out one push to every subscription.

    Returns immediately (never raises) — push is best-effort. Network calls
    happen in a thread so the asyncio loop isn't blocked.
    """
    if not _vapid_ready():
        return
    if quiet_if_session_id is not None and pubsub.subscriber_count(quiet_if_session_id) > 0:
        logger.debug(
            "notifications: suppressing %s for session %d (user is watching)",
            event_type,
            quiet_if_session_id,
        )
        return
    if _check_dedupe(dedupe_key):
        logger.debug("notifications: deduped %s (key=%s)", event_type, dedupe_key)
        return

    payload = {
        "title": title,
        "body": body,
        "url": url,
        "event_type": event_type,
        "tag": tag or event_type,
    }

    with SessionLocal() as db:
        subs = list(db.scalars(select(PushSubscription)))
        if not subs:
            return

        for sub in subs:
            status = await asyncio.to_thread(_send_one, sub, payload)
            if status in (404, 410):
                logger.info(
                    "notifications: dropping dead subscription %d (status=%s)",
                    sub.id,
                    status,
                )
                db.delete(sub)
            elif status is None:
                sub.last_seen_at = utc_now()
            else:
                logger.warning(
                    "notifications: send failed for subscription %d (status=%s)",
                    sub.id,
                    status,
                )
        db.commit()
