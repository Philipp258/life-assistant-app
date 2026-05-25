"""Identity endpoint — assistant name + onboarding state for the frontend.

The frontend calls this on mount to know what to render. Onboarding is a
3-step machine: first the user has to pick a chat provider (the agent
can't run without one), then the agent itself walks them through the
chat onboarding ritual that populates `about_user.md`, then we're done.
While onboarding (any non-`done` state), nav chrome is hidden.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from app.knowledge.identity import resolve_assistant_name
from app.provider_settings.service import is_chat_configured as provider_is_configured
from app.users.service import is_onboarding

OnboardingState = Literal["needs_provider", "needs_chat", "done"]

router = APIRouter(tags=["users"])


def _onboarding_state() -> OnboardingState:
    if not provider_is_configured():
        return "needs_provider"
    if is_onboarding():
        return "needs_chat"
    return "done"


@router.get("/identity")
def identity() -> dict[str, object]:
    state = _onboarding_state()
    return {
        "assistant_name": resolve_assistant_name(),
        "is_onboarding": state != "done",
        "onboarding_state": state,
    }
