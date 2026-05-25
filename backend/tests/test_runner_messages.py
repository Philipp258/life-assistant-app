from __future__ import annotations

from pydantic_ai.exceptions import ModelHTTPError

from app.agent.providers.codex_auth import AuthExpiredError
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


def test_sanitize_error_text_surfaces_codex_auth_cause() -> None:
    try:
        try:
            raise AuthExpiredError("401 Unauthorized")
        except AuthExpiredError as exc:
            raise RuntimeError("Connection error") from exc
    except RuntimeError as exc:
        text = _sanitize_error_text(exc)

    assert text.startswith("AuthExpiredError: Codex CLI session expired")
    assert "codex login --device-auth" in text
