"""Endpoints for the multi-provider settings singleton.

`GET /api/settings/providers` returns one block per provider (configured
flag + non-secret fields) plus the user's preferred chat provider.
`PUT /api/settings/providers/{name}` patches that provider's block.
`PUT /api/settings/providers/preferred-chat` flips which provider chat
uses.
"""

from __future__ import annotations

from typing import Callable, cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.provider_settings import service
from app.provider_settings import verify as credential_verify
from app.provider_settings.models import ProviderSettings
from app.provider_settings.schema import (
    ChatProvider,
    CodexIn,
    CodexOut,
    OpenAIIn,
    OpenAIOut,
    OpenRouterIn,
    OpenRouterOut,
    PreferredChatIn,
    ProviderSettingsOut,
    ZAIIn,
    ZAIOut,
)

router = APIRouter(prefix="/settings/providers", tags=["settings"])

# Stale frontend bundles still call the old singular path. We keep this
# alias so they recover after a deploy instead of crashing on a JSON
# parse error against the SPA HTML. Drop once we're confident no live
# client hits it.
legacy_router = APIRouter(prefix="/settings", tags=["settings"])


def _serialize(row: ProviderSettings) -> ProviderSettingsOut:
    preferred_raw = row.preferred_chat_provider
    preferred: ChatProvider | None = (
        cast(ChatProvider, preferred_raw)
        if preferred_raw in service.SUPPORTED_CHAT_PROVIDERS
        else None
    )
    return ProviderSettingsOut(
        preferred_chat_provider=preferred,
        openai=OpenAIOut(
            configured=bool(row.openai_api_key),
            chat_model=row.openai_chat_model,
        ),
        openrouter=OpenRouterOut(
            configured=bool(row.openrouter_api_key),
            chat_model=row.openrouter_chat_model,
            tts_model=row.openrouter_tts_model,
            tts_voice=row.openrouter_tts_voice,
        ),
        zai=ZAIOut(
            configured=bool(row.zai_api_key),
            endpoint=row.zai_endpoint,
            chat_model=row.zai_chat_model,
        ),
        codex=CodexOut(
            configured=bool(row.codex_auth_json),
            chat_model=row.codex_chat_model,
        ),
    )


def _verify(check: Callable[[], None]) -> None:
    """Run a credential check, turning a rejection into a 400.

    Verification only runs when a *new, non-empty* secret is being set:
    ``None`` means "leave the stored key untouched" and ``""`` means
    "clear it" — neither needs (or can be) verified.
    """
    try:
        check()
    except credential_verify.CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def get_providers(db: Session = Depends(get_session)) -> ProviderSettingsOut:
    return _serialize(service.get_settings(db))


@router.put("/openai")
def put_openai(payload: OpenAIIn, db: Session = Depends(get_session)) -> ProviderSettingsOut:
    if payload.api_key:
        _verify(lambda: credential_verify.verify_openai(payload.api_key))
    row = service.update_openai(db, api_key=payload.api_key, chat_model=payload.chat_model)
    return _serialize(row)


@router.put("/openrouter")
def put_openrouter(
    payload: OpenRouterIn, db: Session = Depends(get_session)
) -> ProviderSettingsOut:
    if payload.api_key:
        _verify(lambda: credential_verify.verify_openrouter(payload.api_key))
    row = service.update_openrouter(
        db,
        api_key=payload.api_key,
        chat_model=payload.chat_model,
        tts_model=payload.tts_model,
        tts_voice=payload.tts_voice,
    )
    return _serialize(row)


@router.put("/zai")
def put_zai(payload: ZAIIn, db: Session = Depends(get_session)) -> ProviderSettingsOut:
    if payload.api_key:
        # Verify against the endpoint being saved, or the stored one if
        # this PATCH only touches the key.
        endpoint = payload.endpoint or service.get_settings(db).zai_endpoint
        _verify(lambda: credential_verify.verify_zai(payload.api_key, endpoint))
    row = service.update_zai(
        db,
        api_key=payload.api_key,
        endpoint=payload.endpoint,
        chat_model=payload.chat_model,
    )
    return _serialize(row)


@router.put("/codex")
def put_codex(payload: CodexIn, db: Session = Depends(get_session)) -> ProviderSettingsOut:
    if payload.auth_json:
        _verify(lambda: credential_verify.verify_codex(payload.auth_json))
    row = service.update_codex(db, auth_json=payload.auth_json, chat_model=payload.chat_model)
    return _serialize(row)


@router.put("/preferred-chat")
def put_preferred_chat(
    payload: PreferredChatIn, db: Session = Depends(get_session)
) -> ProviderSettingsOut:
    # If they're picking a provider, it must actually be configured.
    if payload.preferred_chat_provider is not None:
        row = service.get_settings(db)
        configured = {
            "openai": bool(row.openai_api_key),
            "openrouter": bool(row.openrouter_api_key),
            "zai": bool(row.zai_api_key),
            "codex": bool(row.codex_auth_json),
        }
        if not configured.get(payload.preferred_chat_provider):
            raise HTTPException(
                status_code=400,
                detail=f"{payload.preferred_chat_provider!r} has no credentials configured.",
            )
    row = service.update_preferred_chat(db, preferred=payload.preferred_chat_provider)
    return _serialize(row)


@legacy_router.get("/provider", include_in_schema=False)
def get_providers_legacy(db: Session = Depends(get_session)) -> ProviderSettingsOut:
    return _serialize(service.get_settings(db))
