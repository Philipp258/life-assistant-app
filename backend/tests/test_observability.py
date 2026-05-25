"""Langfuse tracing is opt-in: a full no-op until all three LANGFUSE_*
settings are present, and wired through to pydantic-ai once they are.
Sentry is independent and must stay untouched by the Langfuse gate."""

from __future__ import annotations

import pytest

import app.observability as obs


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs, "_configured", False, raising=True)
    monkeypatch.setattr(obs.settings, "langfuse_public_key", None, raising=False)
    monkeypatch.setattr(obs.settings, "langfuse_secret_key", None, raising=False)
    monkeypatch.setattr(obs.settings, "langfuse_base_url", None, raising=False)
    monkeypatch.setattr(obs.settings, "sentry_dsn", None, raising=False)


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obs.settings, "langfuse_public_key", "pk-lf-x", raising=False)
    monkeypatch.setattr(obs.settings, "langfuse_secret_key", "sk-lf-x", raising=False)
    monkeypatch.setattr(
        obs.settings, "langfuse_base_url", "https://cloud.langfuse.com", raising=False
    )


def test_setup_is_noop_when_unset():
    obs.setup_observability(app=object())
    assert obs._configured is False


def test_setup_is_noop_when_only_partially_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(obs.settings, "langfuse_public_key", "pk-lf-x", raising=False)
    monkeypatch.setattr(obs.settings, "langfuse_secret_key", "sk-lf-x", raising=False)
    # langfuse_base_url still unset.
    obs.setup_observability(app=object())
    assert obs._configured is False


def test_flush_is_noop_when_unset():
    # Must not import langfuse/sentry or raise when everything is disabled.
    obs.flush_observability()


def test_setup_wires_langfuse_and_pydantic_ai(monkeypatch: pytest.MonkeyPatch):
    import langfuse
    import pydantic_ai

    calls: dict[str, object] = {}

    class FakeLangfuse:
        def __init__(self, **kwargs):
            calls["langfuse_kwargs"] = kwargs

    monkeypatch.setattr(langfuse, "Langfuse", FakeLangfuse, raising=True)
    monkeypatch.setattr(
        pydantic_ai.Agent,
        "instrument_all",
        staticmethod(lambda: calls.__setitem__("instrumented", True)),
        raising=True,
    )
    _enable(monkeypatch)
    monkeypatch.setattr(obs.settings, "env", "test", raising=False)

    obs.setup_observability(app=object())

    assert obs._configured is True
    assert calls["instrumented"] is True
    assert calls["langfuse_kwargs"] == {
        "public_key": "pk-lf-x",
        "secret_key": "sk-lf-x",
        "base_url": "https://cloud.langfuse.com",
        "environment": "test",
    }


def test_flush_calls_langfuse_client_when_enabled(monkeypatch: pytest.MonkeyPatch):
    import langfuse

    flushed: dict[str, bool] = {}

    class FakeClient:
        def flush(self):
            flushed["ok"] = True

    monkeypatch.setattr(langfuse, "get_client", lambda: FakeClient(), raising=True)
    _enable(monkeypatch)

    obs.flush_observability()

    assert flushed["ok"] is True
