"""Verify chat credentials before they're stored.

A stored-but-broken credential is worse than no credential. The
onboarding state machine (``app.users.router``) treats *any* non-null
key as "provider configured" and advances to the agent-chat step — and
if the key doesn't actually work, the agent can't start and there's no
UI path back. Verifying at submit time keeps a dead credential from
ever flipping that state. The onboarding escape hatch is the backstop
for everything verification can't catch (a key revoked *after* setup,
quota exhaustion, a provider outage).

Strategy:

OpenAI-compatible API keys (openai, openrouter, zai) are opaque bearer
tokens — the only way to know one works is to ask the provider. We hit
a cheap auth-required endpoint and reject *solely* on an explicit auth
failure (401/403). Anything else — 2xx, 5xx, an unexpected 404, a
network error — is treated as "could not disprove" and allowed through:
we must not block a valid key because the provider or the network
hiccuped, and the escape hatch covers a genuine failure.
"""

from __future__ import annotations

import httpx

from app.agent.providers.openrouter import OPENROUTER_BASE_URL
from app.agent.providers.zai import DEFAULT_ZAI_ENDPOINT, ZAI_ENDPOINT_BASE_URLS

OPENAI_BASE_URL = "https://api.openai.com/v1"
_PROBE_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class CredentialError(Exception):
    """Submitted credential is structurally invalid or rejected by the provider."""


def _probe_openai_compatible(*, api_key: str, base_url: str, path: str) -> None:
    url = base_url.rstrip("/") + path
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_PROBE_TIMEOUT,
        )
    except httpx.HTTPError:
        return  # Can't reach the provider — don't punish a possibly-valid key.
    if resp.status_code in (401, 403):
        raise CredentialError(
            f"The provider rejected this API key (HTTP {resp.status_code}). "
            "Double-check the key and try again."
        )


def verify_openai(api_key: str) -> None:
    _probe_openai_compatible(api_key=api_key, base_url=OPENAI_BASE_URL, path="/models")


def verify_openrouter(api_key: str) -> None:
    # `/key` is auth-required and returns the key's limits; an invalid
    # key gets 401 here. The public `/models` list would not — it
    # answers 200 with no key at all.
    _probe_openai_compatible(api_key=api_key, base_url=OPENROUTER_BASE_URL, path="/key")


def verify_zai(api_key: str, endpoint: str | None) -> None:
    # `endpoint` is normally a short key ("coding-global"), but a raw
    # base URL is also stored/accepted. Resolve either; if it's neither,
    # skip the probe — that's an endpoint mistake, not a bad key, and
    # `build_zai_model` raises a clear error at runtime regardless.
    base_url = ZAI_ENDPOINT_BASE_URLS.get(endpoint or DEFAULT_ZAI_ENDPOINT)
    if base_url is None:
        if endpoint and endpoint.startswith(("http://", "https://")):
            base_url = endpoint
        else:
            return
    _probe_openai_compatible(api_key=api_key, base_url=base_url, path="/models")
