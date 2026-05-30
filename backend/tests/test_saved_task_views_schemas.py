import pytest
from pydantic import ValidationError

from app.saved_task_views.schemas import SavedTaskViewCreate


def test_create_rejects_unknown_group_by():
    with pytest.raises(ValidationError):
        SavedTaskViewCreate(name="x", filters={}, group_by="bogus")


def test_create_rejects_retired_grouping_modes():
    with pytest.raises(ValidationError):
        SavedTaskViewCreate(name="x", filters={}, group_by="status")


def test_create_strips_legacy_label_filter():
    v = SavedTaskViewCreate(name="x", filters={"labels": ["home"]}, group_by="none")
    assert v.filters == {}


def test_filters_rejects_extra_keys():
    with pytest.raises(ValidationError):
        SavedTaskViewCreate(name="x", filters={"haha_unknown": 1}, group_by="none")
