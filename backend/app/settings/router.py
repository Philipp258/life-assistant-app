"""Authenticated HTTP API for DB-backed runtime settings.

Returns plaintext values — these are local app settings, not secrets in
the encryption sense. Auth is enforced by the session middleware mounted
in ``app.main``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.settings import service

router = APIRouter(prefix="/settings/runtime", tags=["settings"])


class RuntimeSettingIn(BaseModel):
    value: str


class RuntimeSettingOut(BaseModel):
    key: str
    value: str


@router.get("")
def get_runtime_settings(db: Session = Depends(get_session)) -> dict[str, str]:
    return service.list_runtime_settings(db)


@router.put("/{key}")
def put_runtime_setting(
    key: str,
    payload: RuntimeSettingIn,
    db: Session = Depends(get_session),
) -> RuntimeSettingOut:
    try:
        value = service.set_runtime_setting(db, key=key, value=payload.value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RuntimeSettingOut(key=key, value=value)
