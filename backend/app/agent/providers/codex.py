"""Codex (ChatGPT subscription) provider — Responses API via Codex CLI OAuth.

The user authenticates locally with the OpenAI ``codex`` CLI, then pastes
the resulting ``~/.codex/auth.json`` blob into the provider settings. We
talk to ``https://chatgpt.com/backend-api/codex/responses`` with the
``access_token`` as a bearer, and refresh through the OAuth refresh
endpoint when the JWT is near expiry. Refreshed tokens are written back
via a caller-supplied async callback (the DB-write path).

Why OpenAIResponsesModel: the Codex endpoint speaks the OpenAI Responses
API event grammar. Using pydantic-ai's built-in model means we get
streaming, function calling, and message conversion for free. Auth
overrides happen through an httpx Auth flow on the underlying client.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from typing_extensions import override
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from app.agent.providers.codex_auth import (
    CodexSession,
    PersistCallback,
    load_session_from_json,
    refresh_session,
)

log = logging.getLogger(__name__)

CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_CODEX_MODEL = "gpt-5.1-codex"

# Codex rejects requests with no `instructions` field ({"detail": "Instructions
# are required"}). pydantic-ai's @agent.system_prompt routes content into the
# input-messages array, leaving `instructions` empty — so we lift the leading
# system-role message into `instructions` ourselves below. Fallback string is
# only used if the agent has no system prompt at all.
_CODEX_DEFAULT_INSTRUCTIONS = "You are a helpful assistant."


class _CodexAuth(httpx.Auth):
    """Inject a fresh ChatGPT bearer + Codex routing headers per request.

    Refresh runs under an asyncio.Lock so concurrent requests don't all
    fire the OAuth refresh endpoint at once when the token expires.
    """

    requires_request_body = False

    def __init__(self, session: CodexSession, persist: PersistCallback | None) -> None:
        self._session = session
        self._persist = persist
        self._lock = asyncio.Lock()

    async def _ensure_fresh(self) -> CodexSession:
        if not self._session.is_expired:
            return self._session
        async with self._lock:
            if self._session.is_expired:
                self._session = await refresh_session(self._session, persist=self._safe_persist)
            return self._session

    async def _safe_persist(self, blob: str) -> None:
        if self._persist is None:
            return
        try:
            await self._persist(blob)
        except Exception:  # pragma: no cover — persist failure is non-fatal
            log.exception("Codex token persist callback failed; refresh will retry next cycle.")

    @override
    async def async_auth_flow(self, request: httpx.Request):
        session = await self._ensure_fresh()
        request.headers["Authorization"] = f"Bearer {session.access_token}"
        if session.account_id:
            request.headers["chatgpt-account-id"] = session.account_id
        request.headers["OpenAI-Beta"] = "responses=experimental"
        yield request

    @override
    def sync_auth_flow(self, request: httpx.Request):  # pragma: no cover
        raise RuntimeError("Codex auth is async-only; openai SDK is async here.")


class _CodexResponsesModel(OpenAIResponsesModel):
    """OpenAIResponsesModel adapted for Codex's Responses endpoint.

    Two upstream quirks are patched here:

    1. Codex rejects requests without `instructions`. `_map_messages` lifts
       the leading system-role message into the `instructions` field and
       removes it from the input array to avoid sending the prompt twice.

    2. Codex rejects non-streamed requests for newer models with
       `400 {"detail": "Stream must be set to true"}`. pydantic-ai still
       calls `model.request()` non-streamed for tool-cycle steps even when
       the outer call is `agent.run_stream_events(...)`. Override
       `request` to delegate to `request_stream` and reassemble the final
       `ModelResponse` from the drained events, so every code path
       (chat router, autonomous runner, tests) sends a streamed POST.
    """

    async def _map_messages(self, messages, model_settings, model_request_parameters):  # type: ignore[override]
        instructions, openai_messages = await super()._map_messages(
            messages, model_settings, model_request_parameters
        )
        if not isinstance(instructions, str) or not instructions:
            lifted: list[str] = []
            remaining = []
            for m in openai_messages:
                if not lifted and m.get("role") == "system":
                    content = m.get("content")
                    if isinstance(content, str):
                        lifted.append(content)
                        continue
                remaining.append(m)
            if lifted:
                instructions = lifted[0]
                openai_messages = remaining
            else:
                instructions = _CODEX_DEFAULT_INSTRUCTIONS
        return instructions, openai_messages

    async def request(self, messages, model_settings, model_request_parameters):  # type: ignore[override]
        async with self.request_stream(
            messages, model_settings, model_request_parameters
        ) as stream:
            async for _ in stream:
                pass
            return stream.get()


def build_codex_model(
    *,
    auth_blob: str,
    model_name: str = DEFAULT_CODEX_MODEL,
    persist: PersistCallback | None = None,
) -> OpenAIResponsesModel:
    """Build a pydantic-ai model wired to the Codex Responses endpoint.

    Args:
        auth_blob: Raw contents of ``~/.codex/auth.json``.
        model_name: Codex model id (e.g. ``gpt-5.1-codex``).
        persist: Optional async callback that receives the updated
            auth.json string after a token refresh, so the caller can
            write it back to wherever it stored the original blob.

    Raises:
        AuthInvalidError: ``auth_blob`` is missing required fields.
    """
    session = load_session_from_json(auth_blob)
    auth = _CodexAuth(session, persist)
    http_client = httpx.AsyncClient(auth=auth, timeout=httpx.Timeout(300, connect=15))
    # The api_key is required by the openai SDK but the httpx Auth
    # rewrites Authorization on every request, so this placeholder is
    # never sent over the wire.
    openai_client = AsyncOpenAI(
        base_url=CODEX_BASE_URL,
        api_key="codex-bearer-overridden-by-httpx-auth",
        http_client=http_client,
    )
    # Codex rejects store=true; force it off via model settings so callers
    # don't have to thread it through every request.
    settings = OpenAIResponsesModelSettings(openai_store=False)
    return _CodexResponsesModel(
        model_name,
        provider=OpenAIProvider(openai_client=openai_client),
        settings=settings,
    )
