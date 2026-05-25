from __future__ import annotations

from datetime import datetime

from app.chat.models import ChatSession
from app.labels.models import Label
from app.saved_task_views.models import SavedTaskView
from app.tasks.models import Task


OLD_TIMESTAMP = datetime(2000, 1, 1, 0, 0, 0)


def test_task_scalar_update_refreshes_updated_at_without_manual_touch(db_session):
    chat = ChatSession(title="old task title")
    db_session.add(chat)
    db_session.flush()
    task = Task(
        title="old task title",
        chat_session_id=chat.id,
        updated_at=OLD_TIMESTAMP,
    )
    db_session.add(task)
    db_session.flush()
    chat.task_id = task.id
    db_session.commit()

    task.title = "new task title"
    db_session.commit()
    db_session.refresh(task)

    assert task.updated_at > OLD_TIMESTAMP


def test_label_update_refreshes_updated_at_without_service_bookkeeping(db_session):
    label = Label(
        slug="chores",
        name="Chores",
        updated_at=OLD_TIMESTAMP,
    )
    db_session.add(label)
    db_session.commit()

    label.name = "House chores"
    db_session.commit()
    db_session.refresh(label)

    assert label.updated_at > OLD_TIMESTAMP


def test_saved_task_view_update_refreshes_updated_at_without_service_bookkeeping(db_session):
    view = SavedTaskView(
        name="Today",
        filters_json={"statuses": ["open"]},
        updated_at=OLD_TIMESTAMP,
    )
    db_session.add(view)
    db_session.commit()

    view.name = "This week"
    db_session.commit()
    db_session.refresh(view)

    assert view.updated_at > OLD_TIMESTAMP
