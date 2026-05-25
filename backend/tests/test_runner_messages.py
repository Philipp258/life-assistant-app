from __future__ import annotations

from pydantic_ai.exceptions import ModelHTTPError

from app.chat.runner.messages import _sanitize_error_text


def test_sanitize_model_http_error_leads_with_provider_detail() -> None:
    exc = ModelHTTPError(
        400,
        "gpt-5-codex",
        {
            "detail": (
                "The 'gpt-5-codex' model is not supported when using Codex with a ChatGPT account."
            )
        },
    )

    text = _sanitize_error_text(exc)

    assert text == (
        "ModelHTTPError 400 (gpt-5-codex): The 'gpt-5-codex' model is not "
        "supported when using Codex with a ChatGPT account."
    )
