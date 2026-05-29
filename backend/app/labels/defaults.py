"""Repo-shipped task labels that must exist on every install."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.labels.models import Label

IMPROVE_LIFE_ASSISTANT_LABEL = "improve-life-assistant"


@dataclass(frozen=True)
class DefaultLabelSpec:
    slug: str
    name: str
    description: str
    color: str | None = None
    icon: str | None = None


DEFAULT_LABELS: tuple[DefaultLabelSpec, ...] = (
    DefaultLabelSpec(
        slug=IMPROVE_LIFE_ASSISTANT_LABEL,
        name="Improve the assistant",
        description="Assistant-owned tasks that turn concrete feedback into durable improvements.",
        color="#7c3aed",
        icon="sparkles",
    ),
)


def ensure_default_labels(db: Session) -> list[str]:
    """Create shipped labels that runtime prompts and routines rely on.

    Labels remain user-owned after creation. If a row with the shipped slug
    already exists, boot seeding leaves its display fields untouched.
    """
    existing = set(db.scalars(select(Label.slug)))
    created: list[str] = []
    for spec in DEFAULT_LABELS:
        if spec.slug in existing:
            continue
        db.add(
            Label(
                slug=spec.slug,
                name=spec.name,
                description=spec.description,
                color=spec.color,
                icon=spec.icon,
            )
        )
        created.append(spec.slug)
    if created:
        db.commit()
    return created
