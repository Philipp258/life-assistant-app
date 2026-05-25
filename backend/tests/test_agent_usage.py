from __future__ import annotations

from app.agent.usage import default_usage_limits
from app.config import settings


def test_default_usage_limits_can_set_explicit_request_cap(monkeypatch):
    monkeypatch.setattr(settings, "agent_request_limit", 250)

    limits = default_usage_limits()

    assert limits.request_limit == 250


def test_default_usage_limits_can_disable_request_cap(monkeypatch):
    monkeypatch.setattr(settings, "agent_request_limit", None)

    limits = default_usage_limits()

    assert limits.request_limit is None
