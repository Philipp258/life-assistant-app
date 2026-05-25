"""OpenAI provider — direct API."""

from __future__ import annotations

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


def build_openai_model(*, api_key: str, model_name: str) -> OpenAIChatModel:
    return OpenAIChatModel(model_name, provider=OpenAIProvider(api_key=api_key))
