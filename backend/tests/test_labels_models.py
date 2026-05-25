from app.labels.models import Label, TaskLabel
from app.tasks.models import Task


def test_label_table_name():
    assert Label.__tablename__ == "labels"


def test_task_label_table_name():
    assert TaskLabel.__tablename__ == "task_labels"


def test_label_has_slug_unique():
    slug_col = Label.__table__.c.slug
    assert slug_col.unique is True


def test_task_has_labels_relationship():
    assert "labels" in Task.__mapper__.relationships.keys()


def test_task_has_no_project_id_column():
    assert "project_id" not in Task.__table__.c
