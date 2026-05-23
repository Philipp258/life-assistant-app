"""Regression tests for UTC timezone serialization across the API.

The DB stores naive UTC datetimes; the API must emit them with an
explicit `Z` (or `+00:00`) marker so browsers don't parse them as local
time. See issue #82.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.datetime_utils import (
    UtcDatetime,
    ensure_aware_utc,
    normalize_to_naive_utc,
    serialize_utc,
    utc_now,
)


# ---------------------------------------------------------------------------
# datetime_utils unit tests
# ---------------------------------------------------------------------------


def test_utc_now_returns_naive_utc():
    now = utc_now()
    assert now.tzinfo is None
    # Within a few seconds of an aware UTC clock — guards against any
    # accidental "use local time" regression.
    aware = datetime.now(UTC).replace(tzinfo=None)
    assert abs((aware - now).total_seconds()) < 5


def test_serialize_utc_treats_naive_as_utc():
    naive = datetime(2026, 5, 7, 21, 25, 0)
    assert serialize_utc(naive) == "2026-05-07T21:25:00Z"


def test_serialize_utc_converts_aware_to_utc():
    # 21:25 UTC == 23:25 +02:00
    aware = datetime(2026, 5, 7, 23, 25, 0, tzinfo=UTC) + timedelta(hours=0)
    assert serialize_utc(aware) == "2026-05-07T23:25:00Z"


def test_serialize_utc_handles_none():
    assert serialize_utc(None) is None


def test_normalize_to_naive_utc_round_trip():
    # Aware non-UTC offset → converted then stripped.
    from datetime import timezone

    plus_two = timezone(timedelta(hours=2))
    aware = datetime(2026, 5, 7, 23, 25, 0, tzinfo=plus_two)
    out = normalize_to_naive_utc(aware)
    assert out == datetime(2026, 5, 7, 21, 25, 0)
    assert out.tzinfo is None


def test_normalize_to_naive_utc_preserves_naive():
    naive = datetime(2026, 5, 7, 21, 25, 0)
    assert normalize_to_naive_utc(naive) is naive


def test_ensure_aware_utc_handles_none():
    assert ensure_aware_utc(None) is None


# ---------------------------------------------------------------------------
# Pydantic schema serialization
# ---------------------------------------------------------------------------


def test_utc_datetime_field_serializes_with_z_suffix():
    from pydantic import BaseModel

    class Demo(BaseModel):
        ts: UtcDatetime | None

    # Naive input — common path: SQLAlchemy returns naive datetimes for
    # `DateTime` columns.
    out = Demo(ts=datetime(2026, 5, 7, 21, 25, 0)).model_dump(mode="json")
    assert out["ts"] == "2026-05-07T21:25:00Z"

    # None passes through.
    assert Demo(ts=None).model_dump(mode="json")["ts"] is None


# ---------------------------------------------------------------------------
# End-to-end API regression
# ---------------------------------------------------------------------------


def test_task_api_response_uses_z_suffix(client):
    """Every datetime field in /api/tasks responses must end with `Z`."""
    create = client.post(
        "/api/tasks",
        json={
            "title": "Local time test",
            "assignee": "assistant",
            "do_at": "2099-04-27T14:30:00",
            "due_at": "2099-04-27T15:00:00",
        },
    )
    assert create.status_code == 201
    body = create.json()
    for field in ("do_at", "due_at", "created_at", "updated_at"):
        value = body[field]
        assert isinstance(value, str), field
        assert value.endswith("Z"), f"{field}={value!r} is missing Z suffix"
        # Re-parsing as aware UTC must succeed and round-trip.
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None

    # GET also returns the same suffix.
    task_id = body["id"]
    fetched = client.get(f"/api/tasks/{task_id}").json()
    for field in ("do_at", "due_at", "created_at", "updated_at"):
        assert fetched[field].endswith("Z")

    # And LIST.
    listed = client.get("/api/tasks").json()["tasks"]
    assert listed[0]["do_at"].endswith("Z")


def test_task_input_with_offset_is_stored_as_utc(client):
    """A client posting a wall-clock + offset must end up stored as the
    equivalent UTC instant — not the wall-clock string with the offset
    silently dropped."""
    # 23:25 in +02:00 == 21:25 UTC.
    create = client.post(
        "/api/tasks",
        json={
            "title": "Berlin evening",
            "assignee": "assistant",
            "do_at": "2099-05-07T23:25:00+02:00",
        },
    )
    assert create.status_code == 201
    body = create.json()
    assert body["do_at"] == "2099-05-07T21:25:00Z"


def test_task_input_with_z_suffix_round_trips(client):
    """The frontend sends `Date.toISOString()` output (`...Z`); ensure
    it round-trips unchanged."""
    create = client.post(
        "/api/tasks",
        json={
            "title": "ISO Z input",
            "assignee": "assistant",
            "do_at": "2099-06-01T08:00:00.000Z",
        },
    )
    assert create.status_code == 201
    assert create.json()["do_at"] == "2099-06-01T08:00:00Z"


def test_task_summary_tool_uses_z_suffix():
    """Agent-facing dict summaries must mark every datetime as UTC so the
    model doesn't interpret a naive string as 'local to wherever I am'."""
    from app.agent.tools.tasks import _summarize

    class FakeTask:
        id = 1
        title = "x"
        description = None
        is_done = False
        assignee = "assistant"
        labels: list = []
        chat_session_id = 11
        do_at = datetime(2026, 5, 7, 21, 25, 0)
        due_at = datetime(2026, 5, 7, 22, 0, 0)
        interval_unit = None
        interval_count = None
        task_log_line = None
        created_at = datetime(2026, 5, 7, 20, 0, 0)
        updated_at = datetime(2026, 5, 7, 20, 0, 0)
        completed_at = None

    summary = _summarize(
        FakeTask(),  # type: ignore[arg-type]
        last_activity_at=datetime(2026, 5, 7, 20, 30, 0),
    )
    assert summary["do_at"] == "2026-05-07T21:25:00Z"
    assert summary["due_at"] == "2026-05-07T22:00:00Z"
    assert summary["completed_at"] is None
    assert summary["last_activity_at"] == "2026-05-07T20:30:00Z"


def test_chat_message_tool_uses_z_suffix(_test_db):
    """`list_chat_messages` (the agent-facing tool) must mark message
    timestamps with `Z` so the model reads them as UTC."""
    from app.agent.tools.chats import do_list_chat_messages
    from app.chat.models import ChatSession, Message

    Session = _test_db
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        sid = chat.id
        row = Message(
            session_id=sid,
            kind="request",
            parts_json={
                "kind": "request",
                "parts": [{"part_kind": "user-prompt", "content": "hi"}],
            },
        )
        row.created_at = datetime(2026, 5, 7, 21, 25, 0)
        s.add(row)
        s.commit()

    out = do_list_chat_messages(sid)
    assert out["messages"][0]["created_at"] == "2026-05-07T21:25:00Z"


def test_knowledge_save_emits_z_suffix(tmp_path, monkeypatch):
    """Knowledge frontmatter timestamps land in API responses; they must
    carry an explicit UTC marker so the editor's "saved at" pill renders
    in local time."""
    import app.knowledge.store as store

    monkeypatch.setattr(store, "KNOWLEDGE_DIR", tmp_path)
    item = store.save_knowledge("note.md", "body", title="Note")
    assert item.created.endswith("Z"), item.created
    assert item.updated.endswith("Z"), item.updated
