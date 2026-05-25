"""Push subscription endpoints.

The browser calls these once after the user grants notification permission.
Single user per Life Assistant instance, so subscriptions aren't scoped per uid -
just per device endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.notifications import service

router = APIRouter(prefix="/push", tags=["push"])


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribePayload(BaseModel):
    endpoint: str
    keys: SubscriptionKeys


class UnsubscribePayload(BaseModel):
    endpoint: str


@router.get("/vapid-public-key")
def vapid_public_key() -> dict[str, str]:
    if not settings.vapid_public_key:
        raise HTTPException(
            status_code=503,
            detail="VAPID not configured. Run gen_vapid_keys.py.",
        )
    return {"key": settings.vapid_public_key}


@router.post("/subscribe", status_code=201)
def subscribe(
    payload: SubscribePayload,
    request: Request,
    db: Session = Depends(get_session),
) -> dict[str, int]:
    user_agent = request.headers.get("user-agent")
    row = service.subscribe(
        db,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=user_agent,
    )
    return {"id": row.id}


@router.delete("/subscribe", status_code=204)
def unsubscribe(
    payload: UnsubscribePayload,
    db: Session = Depends(get_session),
) -> None:
    service.unsubscribe(db, endpoint=payload.endpoint)
