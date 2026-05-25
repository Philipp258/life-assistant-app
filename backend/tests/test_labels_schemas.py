import pytest
from pydantic import ValidationError

from app.labels.schemas import LabelCreate, LabelRead


def test_label_create_requires_slug_and_name():
    label = LabelCreate(slug="travel", name="Travel")
    assert label.slug == "travel"
    assert label.name == "Travel"


def test_label_create_rejects_uppercase_slug():
    with pytest.raises(ValidationError):
        LabelCreate(slug="Travel", name="Travel")


def test_label_create_rejects_space_in_slug():
    with pytest.raises(ValidationError):
        LabelCreate(slug="my label", name="My label")


def test_label_read_validates_from_attributes():
    class Stub:
        id = 1
        slug = "x"
        name = "X"
        description = None
        color = None
        icon = None
        created_at = "2026-05-14T00:00:00"
        updated_at = "2026-05-14T00:00:00"

    LabelRead.model_validate(Stub(), from_attributes=True)
