from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SeededDefault(Base):
    """Ledger of shipped routine defaults that have been materialized once.

    Defaults are keyed by stable code-owned identifiers, not mutable user-visible
    titles. A row means "do not seed this default again"; target_id is best
    effort provenance and may point at an old completed/deleted task or be NULL
    for a tombstone.
    """

    __tablename__ = "seeded_defaults"

    default_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    default_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    target_table: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
