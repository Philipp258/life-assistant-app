"""Z.AI OpenAI-compatible provider.

Endpoint base URLs ported from openclaw/src/plugins/provider-zai-endpoint.ts.
Auto-detect is deferred; users pick an endpoint explicitly per-config.
"""

from __future__ import annotations

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

ZAI_ENDPOINT_BASE_URLS: dict[str, str] = {
    "global": "https://api.z.ai/api/paas/v4",
    "cn": "https://open.bigmodel.cn/api/paas/v4",
    "coding-global": "https://api.z.ai/api/coding/paas/v4",
    "coding-cn": "https://open.bigmodel.cn/api/coding/paas/v4",
}

DEFAULT_ZAI_ENDPOINT = "coding-global"


def build_zai_model(
    *, api_key: str, model_name: str, endpoint: str = DEFAULT_ZAI_ENDPOINT
) -> OpenAIChatModel:
    base_url = ZAI_ENDPOINT_BASE_URLS.get(endpoint)
    if base_url is None:
        raise RuntimeError(
            f"Unknown Z.AI endpoint {endpoint!r}; expected one of {sorted(ZAI_ENDPOINT_BASE_URLS)}."
        )
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(base_url=base_url, api_key=api_key),
    )
