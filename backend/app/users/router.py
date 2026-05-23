"""Identity endpoint — assistant/user names + onboarding state.

The frontend calls this on mount to know what to render. Onboarding is a
3-step machine: first the user has to pick a chat provider (the agent
can't run without one), then the agent itself walks them through the
chat onboarding ritual that stores both identity names + populates
``about_user.md`` / ``behavior.md``, then we're done. While onboarding
(any non-``done`` state), nav chrome is hidden.

Both ``assistant_name`` and ``user_name`` live in ``app_settings``;
``PATCH /api/identity`` updates either or both.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.knowledge import identity
from app.provider_settings.service import is_chat_configured as provider_is_configured
from app.users.service import is_onboarding

OnboardingState = Literal["needs_provider", "needs_chat", "done"]

router = APIRouter(tags=["users"])


class IdentityOut(BaseModel):
    assistant_name: str | None
    user_name: str | None
    is_onboarding: bool
    onboarding_state: OnboardingState


class IdentityPatch(BaseModel):
    assistant_name: str | None = None
    user_name: str | None = None


def _onboarding_state() -> OnboardingState:
    if not provider_is_configured():
        return "needs_provider"
    if is_onboarding():
        return "needs_chat"
    return "done"


def _payload(db: Session) -> IdentityOut:
    state = _onboarding_state()
    return IdentityOut(
        assistant_name=identity.get_assistant_name(db),
        user_name=identity.get_user_name(db),
        is_onboarding=state != "done",
        onboarding_state=state,
    )


@router.get("/identity")
def get_identity(db: Session = Depends(get_session)) -> IdentityOut:
    return _payload(db)


@router.patch("/identity")
def patch_identity(
    body: IdentityPatch, db: Session = Depends(get_session)
) -> IdentityOut:
    if body.assistant_name is None and body.user_name is None:
        raise HTTPException(
            status_code=422, detail="provide assistant_name and/or user_name"
        )
    try:
        if body.assistant_name is not None:
            identity.set_assistant_name(db, body.assistant_name)
        if body.user_name is not None:
            identity.set_user_name(db, body.user_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _payload(db)
