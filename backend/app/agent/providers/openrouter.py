"""OpenRouter provider — OpenAI-compatible, routes to many model backends.

Model name examples: ``openai/gpt-5.1`` or ``openrouter/auto`` to let
OpenRouter pick.
"""

from __future__ import annotations

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def build_openrouter_model(*, api_key: str, model_name: str) -> OpenAIChatModel:
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(base_url=OPENROUTER_BASE_URL, api_key=api_key),
    )
