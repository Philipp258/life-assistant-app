from sqlalchemy import select

from app.saved_task_views.defaults import (
    ASSISTANT_VIEW_FILTERS,
    ASSISTANT_VIEW_ICON,
    ASSISTANT_VIEW_NAME,
    DEFAULT_SAVED_VIEWS,
    DEFAULT_VIEW_FILTERS,
    LEGACY_ASSISTANTS_VIEW_FILTERS,
    LEGACY_ASSISTANTS_VIEW_NAME,
    LEGACY_MAIN_VIEW_FILTERS,
    LEGACY_MAIN_VIEW_NAME,
    DEFAULT_VIEW_ICON,
    DEFAULT_VIEW_NAME,
    INBOX_VIEW_FILTERS,
    INBOX_VIEW_ICON,
    INBOX_VIEW_NAME,
    MINE_VIEW_FILTERS,
    MINE_VIEW_ICON,
    MINE_VIEW_NAME,
    TODAY_VIEW_FILTERS,
    TODAY_VIEW_ICON,
    TODAY_VIEW_NAME,
    ensure_default_saved_views,
)
from app.saved_task_views.models import SavedTaskView


def test_table_name():
    assert SavedTaskView.__tablename__ == "saved_task_views"


def test_filters_is_json():
    col = SavedTaskView.__table__.c.filters_json
    assert "JSON" in str(col.type).upper() or "TEXT" in str(col.type).upper()


def test_ensure_default_saved_views_seeds_inbox_mine_assistant_on_empty_db(_test_db):
    """Formerly seeded by the aff49964abdc migration; now boot seeding."""
    with _test_db() as db:
        created = ensure_default_saved_views(db)
        assert created is True

        views = list(db.scalars(select(SavedTaskView).order_by(SavedTaskView.sort_index)))
        assert [view.name for view in views] == [
            INBOX_VIEW_NAME,
            MINE_VIEW_NAME,
            ASSISTANT_VIEW_NAME,
        ]
        assert [view.icon for view in views] == [
            INBOX_VIEW_ICON,
            MINE_VIEW_ICON,
            ASSISTANT_VIEW_ICON,
        ]
        assert [view.filters_json for view in views] == [
            INBOX_VIEW_FILTERS,
            MINE_VIEW_FILTERS,
            ASSISTANT_VIEW_FILTERS,
        ]
        assert [view.group_by for view in views] == ["none", "none", "none"]
        assert [view.sort_index for view in views] == [0, 1, 2]
        assert [view.is_default for view in views] == [True, False, False]
        assert len(views) == len(DEFAULT_SAVED_VIEWS)


def test_ensure_default_saved_views_replaces_untouched_legacy_today(_test_db):
    with _test_db() as db:
        db.add(
            SavedTaskView(
                name=TODAY_VIEW_NAME,
                icon=TODAY_VIEW_ICON,
                filters_json=TODAY_VIEW_FILTERS,
                group_by="none",
                sort_index=0,
                is_default=True,
            )
        )
        db.commit()

        created = ensure_default_saved_views(db)

        assert created is True
        names = [
            view.name
            for view in db.scalars(select(SavedTaskView).order_by(SavedTaskView.sort_index))
        ]
        assert names == [INBOX_VIEW_NAME, MINE_VIEW_NAME, ASSISTANT_VIEW_NAME]


def test_ensure_default_saved_views_replaces_untouched_legacy_tasks(_test_db):
    with _test_db() as db:
        db.add(
            SavedTaskView(
                name=DEFAULT_VIEW_NAME,
                icon=DEFAULT_VIEW_ICON,
                filters_json=DEFAULT_VIEW_FILTERS,
                group_by="none",
                sort_index=0,
                is_default=True,
            )
        )
        db.commit()

        created = ensure_default_saved_views(db)

        assert created is True
        names = [
            view.name
            for view in db.scalars(select(SavedTaskView).order_by(SavedTaskView.sort_index))
        ]
        assert names == [INBOX_VIEW_NAME, MINE_VIEW_NAME, ASSISTANT_VIEW_NAME]


def test_ensure_default_saved_views_replaces_untouched_legacy_main_assistants(_test_db):
    with _test_db() as db:
        db.add_all(
            [
                SavedTaskView(
                    name=LEGACY_MAIN_VIEW_NAME,
                    icon=None,
                    filters_json=LEGACY_MAIN_VIEW_FILTERS,
                    group_by="assignee",
                    sort_index=0,
                    is_default=True,
                ),
                SavedTaskView(
                    name=LEGACY_ASSISTANTS_VIEW_NAME,
                    icon=None,
                    filters_json=LEGACY_ASSISTANTS_VIEW_FILTERS,
                    group_by="assignee",
                    sort_index=1,
                    is_default=False,
                ),
            ]
        )
        db.commit()

        created = ensure_default_saved_views(db)

        assert created is True
        views = list(db.scalars(select(SavedTaskView).order_by(SavedTaskView.sort_index)))
        assert [view.name for view in views] == [
            INBOX_VIEW_NAME,
            MINE_VIEW_NAME,
            ASSISTANT_VIEW_NAME,
        ]
        assert [view.filters_json for view in views] == [
            INBOX_VIEW_FILTERS,
            MINE_VIEW_FILTERS,
            ASSISTANT_VIEW_FILTERS,
        ]
        assert [view.group_by for view in views] == ["none", "none", "none"]
        assert [view.is_default for view in views] == [True, False, False]


def test_ensure_default_saved_views_is_noop_when_views_exist(_test_db):
    """Saved views are user-owned once any view exists."""
    with _test_db() as db:
        ensure_default_saved_views(db)
        # User deletes defaults, makes their own.
        db.query(SavedTaskView).delete()
        db.add(SavedTaskView(name="Mine", filters_json={}, group_by="none"))
        db.commit()

        created = ensure_default_saved_views(db)

        assert created is False
        names = [view.name for view in db.scalars(select(SavedTaskView))]
        assert names == ["Mine"]


def test_default_saved_views_are_recreated_if_all_views_are_missing(_test_db):
    with _test_db() as db:
        ensure_default_saved_views(db)
        db.query(SavedTaskView).delete()
        db.commit()

        created = ensure_default_saved_views(db)

        assert created is True
        names = [
            view.name
            for view in db.scalars(select(SavedTaskView).order_by(SavedTaskView.sort_index))
        ]
        assert names == [INBOX_VIEW_NAME, MINE_VIEW_NAME, ASSISTANT_VIEW_NAME]
