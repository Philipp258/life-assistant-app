"""Shared pydantic-ai usage limits for Life Assistant agent runs."""

from __future__ import annotations

from pydantic_ai.usage import UsageLimits

from app.config import settings


def default_usage_limits() -> UsageLimits:
    """Return Life Assistant's explicit per-run usage limits.

    pydantic-ai defaults ``request_limit`` to 50 when no ``UsageLimits`` is
    supplied. That is too low for Life Assistant's long autonomous task turns, where each
    tool-call round trip can consume another model request. We raise it to an
    explicit, higher cap (``settings.agent_request_limit``) that still acts as a
    hard backstop against a runaway tool-call loop. Setting it to ``None``
    disables the request-count cap entirely. Token/provider limits still apply.
    """

    return UsageLimits(request_limit=settings.agent_request_limit)
