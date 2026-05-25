"""Store Codex credentials in typed columns.

Revision ID: c8d4e9f2a713
Revises: 9c1de4f7b201
Create Date: 2026-05-25 00:00:00.000000
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c8d4e9f2a713"
down_revision: Union[str, Sequence[str], None] = "9c1de4f7b201"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _decode_jwt_payload(jwt: str) -> dict[str, Any]:
    parts = jwt.split(".")
    if len(parts) != 3:
        raise ValueError("invalid JWT")
    payload = parts[1]
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    return json.loads(base64.urlsafe_b64decode(payload))


def _parse_jwt_expiry(jwt: str) -> datetime:
    claims = _decode_jwt_payload(jwt)
    exp = claims.get("exp")
    if exp is None:
        raise ValueError("missing exp")
    return datetime.fromtimestamp(int(exp), tz=timezone.utc)


def _parse_iso_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_id_claims(jwt: Any) -> tuple[str | None, str | None]:
    if not isinstance(jwt, str) or not jwt:
        return None, None
    try:
        claims = _decode_jwt_payload(jwt)
    except (ValueError, json.JSONDecodeError):
        return None, None
    auth_claims = claims.get("https://api.openai.com/auth", {})
    if not isinstance(auth_claims, dict):
        return None, None
    account_id = auth_claims.get("chatgpt_account_id")
    plan_raw = auth_claims.get("chatgpt_plan_type")
    plan_type = None
    if isinstance(plan_raw, str):
        plan_type = plan_raw
    elif isinstance(plan_raw, dict):
        plan_type = plan_raw.get("name") or plan_raw.get("display_name")
    return (
        account_id if isinstance(account_id, str) else None,
        plan_type if isinstance(plan_type, str) else None,
    )


def _extract_codex_fields(blob: str | None) -> dict[str, Any] | None:
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(access_token, str) or not access_token:
        return None
    if not isinstance(refresh_token, str) or not refresh_token:
        return None
    try:
        expires_at = _parse_jwt_expiry(access_token)
    except (ValueError, json.JSONDecodeError):
        expires_at = datetime.fromtimestamp(0, tz=timezone.utc)

    id_token = tokens.get("id_token")
    account_id = tokens.get("account_id")
    id_account_id, plan_type = _parse_id_claims(id_token)
    if not isinstance(account_id, str) or not account_id:
        account_id = id_account_id

    auth_mode = data.get("auth_mode")
    if not isinstance(auth_mode, str):
        auth_mode = None

    return {
        "codex_auth_mode": auth_mode,
        "codex_access_token": access_token,
        "codex_refresh_token": refresh_token,
        "codex_id_token": id_token if isinstance(id_token, str) and id_token else None,
        "codex_account_id": account_id,
        "codex_plan_type": plan_type,
        "codex_expires_at": expires_at,
        "codex_last_refresh": _parse_iso_datetime(data.get("last_refresh")),
    }


def upgrade() -> None:
    op.add_column("provider_settings", sa.Column("codex_auth_mode", sa.String(length=32)))
    op.add_column("provider_settings", sa.Column("codex_access_token", sa.Text()))
    op.add_column("provider_settings", sa.Column("codex_refresh_token", sa.Text()))
    op.add_column("provider_settings", sa.Column("codex_id_token", sa.Text()))
    op.add_column("provider_settings", sa.Column("codex_account_id", sa.String(length=255)))
    op.add_column("provider_settings", sa.Column("codex_plan_type", sa.String(length=128)))
    op.add_column("provider_settings", sa.Column("codex_expires_at", sa.DateTime(timezone=True)))
    op.add_column("provider_settings", sa.Column("codex_last_refresh", sa.DateTime(timezone=True)))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, codex_auth_json FROM provider_settings")
    ).fetchall()
    for row in rows:
        fields = _extract_codex_fields(row.codex_auth_json)
        if fields is None:
            continue
        conn.execute(
            sa.text(
                """
                UPDATE provider_settings
                SET codex_auth_mode = :codex_auth_mode,
                    codex_access_token = :codex_access_token,
                    codex_refresh_token = :codex_refresh_token,
                    codex_id_token = :codex_id_token,
                    codex_account_id = :codex_account_id,
                    codex_plan_type = :codex_plan_type,
                    codex_expires_at = :codex_expires_at,
                    codex_last_refresh = :codex_last_refresh
                WHERE id = :id
                """
            ),
            {"id": row.id, **fields},
        )

    with op.batch_alter_table("provider_settings") as batch_op:
        batch_op.drop_column("codex_auth_json")


def downgrade() -> None:
    op.add_column("provider_settings", sa.Column("codex_auth_json", sa.Text()))
    with op.batch_alter_table("provider_settings") as batch_op:
        batch_op.drop_column("codex_last_refresh")
        batch_op.drop_column("codex_expires_at")
        batch_op.drop_column("codex_plan_type")
        batch_op.drop_column("codex_account_id")
        batch_op.drop_column("codex_id_token")
        batch_op.drop_column("codex_refresh_token")
        batch_op.drop_column("codex_access_token")
        batch_op.drop_column("codex_auth_mode")
