"""Tests for the `search_main_chat_history` agent tool.

Covers the pure `do_read_archived_messages` function (registered to the
agent as `search_main_chat_history`): it returns a paginated page of
grep-style matches from the singleton main chat. Each match wraps an
archived/compacted row in `context` archive rows before and after. Live
(un-stamped) messages and rows from non-main sessions must never leak
into the result.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.agent.tools.archived_messages import do_read_archived_messages
from app.chat.models import ChatSession, Message
from app.chat.service import get_or_create_main_session
from app.datetime_utils import utc_now


def _main_id(Session) -> int:
    with Session() as s:
        return get_or_create_main_session(s).id


def _make_task_session(Session) -> int:
    with Session() as s:
        chat = ChatSession()  # default kind="task"
        s.add(chat)
        s.commit()
        return chat.id


def _seed(
    Session,
    session_id: int,
    *,
    text: str,
    kind: str = "request",
    created_at: datetime | None = None,
    archived_at: datetime | None = None,
    compacted_at: datetime | None = None,
) -> int:
    parts = (
        [{"part_kind": "user-prompt", "content": text}]
        if kind == "request"
        else [{"part_kind": "text", "content": text}]
    )
    with Session() as s:
        row = Message(
            session_id=session_id,
            kind=kind,
            parts_json={"kind": kind, "parts": parts},
        )
        if created_at is not None:
            row.created_at = created_at
        if archived_at is not None:
            row.archived_at = archived_at
        if compacted_at is not None:
            row.compacted_at = compacted_at
        s.add(row)
        s.commit()
        return row.id


def _texts(result) -> list[str]:
    return [m["match"]["text"] for m in result["matches"]]


def test_returns_archived_and_compacted_with_via_field(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    now = utc_now()
    archived_id = _seed(Session, sid, text="reset-me", archived_at=now)
    compacted_id = _seed(Session, sid, text="rolled-up", compacted_at=now)
    _seed(Session, sid, text="live")  # must NOT appear

    out = do_read_archived_messages()
    by_id = {m["match"]["id"]: m["match"] for m in out["matches"]}
    assert set(by_id) == {archived_id, compacted_id}
    assert by_id[archived_id]["archived_via"] == "archived"
    assert by_id[archived_id]["text"] == "reset-me"
    assert by_id[compacted_id]["archived_via"] == "compacted"
    assert by_id[compacted_id]["text"] == "rolled-up"


def test_archived_wins_over_compacted_when_both_set(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    now = utc_now()
    rid = _seed(Session, sid, text="x", compacted_at=now, archived_at=now)
    out = do_read_archived_messages()
    assert len(out["matches"]) == 1
    assert out["matches"][0]["match"]["id"] == rid
    assert out["matches"][0]["match"]["archived_via"] == "archived"


def test_no_archive_returns_empty_page(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    _seed(Session, sid, text="live-only")
    out = do_read_archived_messages()
    assert out["matches"] == []
    assert out["total"] == 0
    assert out["has_more"] is False


def test_before_after_filters(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    old = stamp - timedelta(hours=3)
    mid = stamp - timedelta(hours=1)
    new = stamp
    _seed(Session, sid, text="old", created_at=old, archived_at=stamp)
    _seed(Session, sid, text="mid", created_at=mid, archived_at=stamp)
    _seed(Session, sid, text="new", created_at=new, archived_at=stamp)

    cut = stamp - timedelta(minutes=30)
    assert _texts(do_read_archived_messages(before=cut)) == ["old", "mid"]
    assert _texts(do_read_archived_messages(after=cut)) == ["new"]


def test_before_after_accept_offset_aware_datetime(_test_db):
    """Regression: pydantic-ai parses ISO timestamps with `Z` / offset
    as timezone-aware datetimes. The DB stores naive UTC, so we must
    normalize at the tool boundary or the comparison breaks."""
    from datetime import UTC

    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    old = stamp - timedelta(hours=3)
    mid = stamp - timedelta(hours=1)
    new = stamp
    _seed(Session, sid, text="old", created_at=old, archived_at=stamp)
    _seed(Session, sid, text="mid", created_at=mid, archived_at=stamp)
    _seed(Session, sid, text="new", created_at=new, archived_at=stamp)

    cut_aware = stamp.replace(tzinfo=UTC) - timedelta(minutes=30)
    assert _texts(do_read_archived_messages(before=cut_aware)) == ["old", "mid"]
    assert _texts(do_read_archived_messages(after=cut_aware)) == ["new"]


def test_limit_caps_results(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    for i in range(5):
        _seed(
            Session,
            sid,
            text=f"m{i}",
            created_at=stamp + timedelta(seconds=i),
            archived_at=stamp,
        )
    out = do_read_archived_messages(limit=2)
    assert _texts(out) == ["m0", "m1"]
    assert out["total"] == 5
    assert out["has_more"] is True


def test_invalid_limit_returns_error(_test_db):
    out = do_read_archived_messages(limit=0)
    assert "error" in out


def test_invalid_offset_returns_error(_test_db):
    out = do_read_archived_messages(offset=-1)
    assert "error" in out


def test_invalid_context_returns_error(_test_db):
    out = do_read_archived_messages(context=-1)
    assert "error" in out


def test_other_session_archives_do_not_leak(_test_db):
    Session = _test_db
    main_sid = _main_id(Session)
    task_sid = _make_task_session(Session)
    stamp = utc_now()
    _seed(Session, main_sid, text="main-archived", archived_at=stamp)
    _seed(Session, task_sid, text="task-archived", archived_at=stamp)

    assert _texts(do_read_archived_messages()) == ["main-archived"]


def test_query_filters_to_substring_matches(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    _seed(Session, sid, text="we discussed sourdough starter ratios", archived_at=stamp)
    _seed(Session, sid, text="bug in the auth flow", archived_at=stamp)
    _seed(Session, sid, text="more sourdough notes", archived_at=stamp)

    out = do_read_archived_messages(query="sourdough", context=0)
    assert _texts(out) == [
        "we discussed sourdough starter ratios",
        "more sourdough notes",
    ]
    assert out["total"] == 2


def test_query_is_case_insensitive(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    _seed(Session, sid, text="Project Phoenix kickoff", archived_at=stamp)
    _seed(Session, sid, text="unrelated chatter", archived_at=stamp)

    out = do_read_archived_messages(query="phoenix", context=0)
    assert _texts(out) == ["Project Phoenix kickoff"]


def test_query_no_match_returns_empty(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    _seed(Session, sid, text="hello world", archived_at=stamp)

    out = do_read_archived_messages(query="nothing here")
    assert out["matches"] == []
    assert out["total"] == 0


def test_query_combined_with_time_window(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    old = stamp - timedelta(hours=2)
    new = stamp
    _seed(Session, sid, text="early apple", created_at=old, archived_at=stamp)
    _seed(Session, sid, text="late apple", created_at=new, archived_at=stamp)

    out = do_read_archived_messages(query="apple", after=stamp - timedelta(hours=1), context=0)
    assert _texts(out) == ["late apple"]


def test_query_includes_grep_style_context(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    for i, text in enumerate(["a", "b", "needle", "d", "e"]):
        _seed(
            Session,
            sid,
            text=text,
            created_at=stamp + timedelta(seconds=i),
            archived_at=stamp,
        )

    out = do_read_archived_messages(query="needle", context=2)
    assert len(out["matches"]) == 1
    hit = out["matches"][0]
    assert [r["text"] for r in hit["before"]] == ["a", "b"]
    assert hit["match"]["text"] == "needle"
    assert [r["text"] for r in hit["after"]] == ["d", "e"]


def test_context_clamps_at_archive_boundaries(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    _seed(Session, sid, text="needle", created_at=stamp, archived_at=stamp)
    _seed(Session, sid, text="b", created_at=stamp + timedelta(seconds=1), archived_at=stamp)

    out = do_read_archived_messages(query="needle", context=5)
    hit = out["matches"][0]
    assert hit["before"] == []
    assert [r["text"] for r in hit["after"]] == ["b"]


def test_offset_pages_through_matches(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    for i in range(4):
        _seed(
            Session,
            sid,
            text=f"needle {i}",
            created_at=stamp + timedelta(seconds=i),
            archived_at=stamp,
        )

    page1 = do_read_archived_messages(query="needle", limit=2, offset=0, context=0)
    assert _texts(page1) == ["needle 0", "needle 1"]
    assert page1["total"] == 4
    assert page1["has_more"] is True

    page2 = do_read_archived_messages(query="needle", limit=2, offset=2, context=0)
    assert _texts(page2) == ["needle 2", "needle 3"]
    assert page2["has_more"] is False


def test_no_query_paginates_flat(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    for i in range(3):
        _seed(
            Session,
            sid,
            text=f"row{i}",
            created_at=stamp + timedelta(seconds=i),
            archived_at=stamp,
        )

    out = do_read_archived_messages(limit=2, offset=1)
    assert _texts(out) == ["row1", "row2"]
    # Without `query`, before/after stay empty — context only applies to hits.
    assert all(m["before"] == [] and m["after"] == [] for m in out["matches"])
    assert out["total"] == 3
    assert out["has_more"] is False


def test_context_excludes_live_messages(_test_db):
    Session = _test_db
    sid = _main_id(Session)
    stamp = utc_now()
    _seed(Session, sid, text="archived-before", created_at=stamp, archived_at=stamp)
    _seed(
        Session,
        sid,
        text="needle",
        created_at=stamp + timedelta(seconds=1),
        archived_at=stamp,
    )
    _seed(Session, sid, text="LIVE row", created_at=stamp + timedelta(seconds=2))
    _seed(
        Session,
        sid,
        text="archived-after",
        created_at=stamp + timedelta(seconds=3),
        archived_at=stamp,
    )

    out = do_read_archived_messages(query="needle", context=2)
    hit = out["matches"][0]
    assert [r["text"] for r in hit["before"]] == ["archived-before"]
    assert [r["text"] for r in hit["after"]] == ["archived-after"]
