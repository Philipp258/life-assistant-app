"""Cookie-session login endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth import rate_limit
from app.db import SessionLocal
from app.users.service import ensure_user, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request) -> dict[str, bool]:
    ip = request.client.host if request.client else "unknown"
    retry_after = rate_limit.check_locked(ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too_many_attempts",
            headers={"Retry-After": str(retry_after)},
        )
    with SessionLocal() as db:
        user = ensure_user(db)
        ok = verify_password(body.password, user.password_hash)
        if not ok:
            rate_limit.register_failure(ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_password",
            )
        rate_limit.register_success(ip)
        request.session["uid"] = user.id
        request.session["iat"] = int(time.time())
    return {"ok": True}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(request: Request) -> dict[str, bool]:
    return {"authenticated": bool(request.session.get("uid"))}
