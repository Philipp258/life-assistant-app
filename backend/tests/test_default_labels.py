from __future__ import annotations

from sqlalchemy import select

from app.labels.defaults import (
    DEFAULT_LABELS,
    IMPROVE_LIFE_ASSISTANT_LABEL,
    ensure_default_labels,
)
from app.labels.models import Label
from app.tasks.schemas import TaskCreate
from app.tasks.service import create_task


def test_ensure_default_labels_creates_improvement_label(_test_db):
    with _test_db() as db:
        created = ensure_default_labels(db)

    assert created == [IMPROVE_LIFE_ASSISTANT_LABEL]

    with _test_db() as db:
        labels = list(db.scalars(select(Label).order_by(Label.slug)))
        assert len(labels) == len(DEFAULT_LABELS)
        assert labels[0].slug == IMPROVE_LIFE_ASSISTANT_LABEL
        assert labels[0].name == "Improve the assistant"


def test_ensure_default_labels_is_idempotent_and_preserves_user_fields(_test_db):
    with _test_db() as db:
        db.add(
            Label(
                slug=IMPROVE_LIFE_ASSISTANT_LABEL,
                name="My improvement lane",
                description="custom",
                color="#111111",
                icon="custom",
            )
        )
        db.commit()

        created = ensure_default_labels(db)

    assert created == []

    with _test_db() as db:
        label = db.scalars(select(Label).where(Label.slug == IMPROVE_LIFE_ASSISTANT_LABEL)).one()
        assert label.name == "My improvement lane"
        assert label.description == "custom"
        assert label.color == "#111111"
        assert label.icon == "custom"


def test_seeded_improvement_label_allows_labeled_task_creation(_test_db):
    with _test_db() as db:
        ensure_default_labels(db)
        task = create_task(
            db,
            TaskCreate(
                title="Improve suggestion behavior",
                description="Evidence.",
                assignee="assistant",
                labels=[IMPROVE_LIFE_ASSISTANT_LABEL],
            ),
        )

    assert [label.slug for label in task.labels] == [IMPROVE_LIFE_ASSISTANT_LABEL]
