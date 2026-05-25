"""Optional observability integrations. No-op unless configured by env vars.

Tracing goes to Langfuse over OpenTelemetry: pydantic-ai is OTel-instrumented,
and the Langfuse client wires up the global tracer provider + OTLP exporter on
init, so ``Agent.instrument_all()`` makes every agent emit spans into it.
Sentry (errors/perf) is a separate, independent integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI

_configured = False
_sentry_configured = False


def _langfuse_enabled() -> bool:
    return bool(
        settings.langfuse_public_key and settings.langfuse_secret_key and settings.langfuse_base_url
    )


def setup_sentry() -> None:
    global _sentry_configured
    if _sentry_configured or not settings.sentry_dsn:
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        release=settings.sentry_release,
        send_default_pii=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
    )

    _sentry_configured = True


def setup_observability(app: "FastAPI") -> None:
    # `app` is unused: with the OTLP path FastAPI/SQLAlchemy/httpx would each
    # need their own opentelemetry-instrumentation-* package. Tracing the
    # pydantic-ai agent is the high-signal piece; the rest is a possible
    # follow-up. Signature kept so main.py needs no change.
    global _configured
    if _configured or not _langfuse_enabled():
        return

    from langfuse import Langfuse
    from pydantic_ai import Agent

    Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
        environment=settings.env,
    )
    Agent.instrument_all()

    _configured = True


def flush_observability() -> None:
    if _langfuse_enabled():
        from langfuse import get_client

        get_client().flush()

    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.flush(timeout=2)
