"""First-boot main-session greeting."""

from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.models import Message
from app.chat.service.sessions import get_or_create_main_session
from app.chat.service.writes import save_new_messages
from app.users.service import is_onboarding

ONBOARDING_GREETING = (
    "Welcome! I'm your new personal assistant. I'll keep track of tasks, "
    "remember what matters, and adapt to how you like to work. To get "
    "started — what would you like to call me?"
)


def inject_onboarding_greeting_if_needed(session: Session) -> bool:
    """Insert a hardcoded assistant greeting into the main session iff the
    user is mid-onboarding and the main session has no messages yet.

    Idempotent: once any message exists in the main session, this is a
    no-op. Returns True if a row was inserted, False otherwise.
    """
    if not is_onboarding():
        return False
    main = get_or_create_main_session(session)
    existing = session.scalars(
        select(Message).where(Message.session_id == main.id).limit(1)
    ).first()
    if existing is not None:
        return False
    greeting = ModelResponse(parts=[TextPart(content=ONBOARDING_GREETING)])
    save_new_messages(session, main.id, [greeting])
    return True
