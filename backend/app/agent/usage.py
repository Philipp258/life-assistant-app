"""Shared pydantic-ai usage limits for Life Assistant agent runs."""

from __future__ import annotations

from pydantic_ai.usage import UsageLimits

from app.config import settings


def default_usage_limits() -> UsageLimits:
    """Return Life Assistant's explicit per-run usage limits.

    pydantic-ai defaults ``request_limit`` to 50 when no ``UsageLimits`` is
    supplied. That is too low for Life Assistant's long autonomous task turns, where each
    tool-call round trip can consume another model request. Supplying
    ``request_limit=None`` disables that request-count cap explicitly instead of
    inheriting the library default silently. Token/provider limits still apply.
    """

    return UsageLimits(request_limit=settings.agent_request_limit)
