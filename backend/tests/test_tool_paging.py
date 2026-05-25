"""Pagination contract for context-heavy agent tools.

The point of paging these tools is that no single call can flood the
agent's context, yet nothing is lost — every byte stays reachable by
stepping `offset`. These tests pin both halves of that contract:
envelope correctness, and losslessness across pages.
"""

from __future__ import annotations

from pathlib import Path

from app.agent.tools import fs as fs_tools
from app.agent.tools._paging import normalize_page, paginate, window_text
from app.agent.tools.knowledge import do_read_knowledge


# --- pure helpers -----------------------------------------------------


def test_normalize_page_coerces_bad_input() -> None:
    assert normalize_page(-5, 10, default_limit=50, max_limit=200) == (0, 10)
    # limit<=0 means "give me the default page", not an empty page.
    assert normalize_page(3, 0, default_limit=50, max_limit=200) == (3, 50)
    assert normalize_page(3, -1, default_limit=50, max_limit=200) == (3, 50)


def test_normalize_page_clamps_limit_to_max() -> None:
    # Model-controlled args: a huge limit must not flood context.
    assert normalize_page(0, 1_000_000, default_limit=50, max_limit=200) == (0, 200)
    assert normalize_page(0, 200, default_limit=50, max_limit=200) == (0, 200)
    assert normalize_page(0, 201, default_limit=50, max_limit=200) == (0, 200)
    # default itself is never above max, so limit<=0 stays at default.
    assert normalize_page(0, 0, default_limit=50, max_limit=200) == (0, 50)


def test_paginate_envelope_and_stepping() -> None:
    items = list(range(25))

    p1 = paginate(items, 0, 10)
    assert p1["items"] == list(range(10))
    assert p1["total"] == 25
    assert p1["has_more"] is True
    assert p1["next_offset"] == 10

    p3 = paginate(items, 20, 10)
    assert p3["items"] == list(range(20, 25))
    assert p3["has_more"] is False
    assert p3["next_offset"] is None


def test_paginate_offset_past_end_is_empty_not_error() -> None:
    p = paginate([1, 2, 3], 99, 10)
    assert p["items"] == []
    assert p["total"] == 3
    assert p["has_more"] is False
    assert p["next_offset"] is None


def test_window_text_is_lossless_across_pages() -> None:
    body = "".join(f"line {i}\n" for i in range(500))
    rebuilt = ""
    offset, limit = 0, 128
    guard = 0
    while True:
        win = window_text(body, offset, limit)
        rebuilt += win["text"]
        assert win["total_chars"] == len(body)
        if not win["has_more"]:
            assert win["next_offset"] is None
            break
        offset = win["next_offset"]
        guard += 1
        assert guard < 1000, "windowing failed to terminate"
    assert rebuilt == body


# --- grep: page, never silently truncate ------------------------------


def test_grep_paginates_instead_of_truncating(tmp_path: Path) -> None:
    target = tmp_path / "many.txt"
    target.write_text("".join(f"needle {i}\n" for i in range(120)))

    page1 = fs_tools.do_grep("needle", path=str(tmp_path), offset=0, limit=40)
    assert "error" not in page1
    assert page1["total"] == 120
    assert len(page1["matches"]) == 40
    assert page1["has_more"] is True
    assert page1["next_offset"] == 40
    assert page1["scan_capped"] is False

    seen = list(page1["matches"])
    offset = page1["next_offset"]
    while offset is not None:
        nxt = fs_tools.do_grep("needle", path=str(tmp_path), offset=offset, limit=40)
        seen.extend(nxt["matches"])
        offset = nxt["next_offset"]

    # Every match reachable by paging — nothing dropped to a silent cap.
    assert len(seen) == 120
    assert {m["line"] for m in seen} == set(range(1, 121))


def test_grep_clamps_limit_to_max(tmp_path: Path) -> None:
    target = tmp_path / "many.txt"
    target.write_text("".join(f"needle {i}\n" for i in range(120)))

    # A model asking for a million matches in one call gets the page
    # capped at GREP_PAGE_MAX, not the whole haystack.
    out = fs_tools.do_grep("needle", path=str(tmp_path), limit=1_000_000)
    assert "error" not in out
    assert out["limit"] == fs_tools.GREP_PAGE_MAX
    # 120 < cap, so all returned here, but `limit` proves the clamp.
    assert len(out["matches"]) == 120


def test_grep_scan_ceiling_caps_total(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fs_tools, "GREP_SCAN_CEILING", 25)
    target = tmp_path / "many.txt"
    target.write_text("".join(f"needle {i}\n" for i in range(120)))

    out = fs_tools.do_grep("needle", path=str(tmp_path), limit=fs_tools.GREP_PAGE_DEFAULT)
    # Scan stopped at the ceiling: total reflects only what was scanned
    # and scan_capped warns the caller not to trust it / to narrow.
    assert out["total"] == 25
    assert out["scan_capped"] is True


# --- read_knowledge: windowed body, lossless --------------------------


def test_read_knowledge_windows_body_losslessly(tmp_path, monkeypatch) -> None:
    import app.knowledge.store as store

    monkeypatch.setattr(store, "KNOWLEDGE_DIR", tmp_path)
    big = "".join(f"para {i} lorem ipsum\n" for i in range(2000))
    store.save_knowledge("notes/big.md", big, title="Big")

    first = do_read_knowledge("notes/big.md", offset=0, limit=500)
    assert first["total_chars"] == len(big)
    assert first["has_more"] is True
    assert len(first["body"]) == 500

    rebuilt = ""
    offset: int | None = 0
    while offset is not None:
        win = do_read_knowledge("notes/big.md", offset=offset, limit=500)
        rebuilt += win["body"]
        offset = win["next_offset"]
    assert rebuilt == big


def test_read_knowledge_default_is_single_page_for_small_entry(tmp_path, monkeypatch) -> None:
    import app.knowledge.store as store

    monkeypatch.setattr(store, "KNOWLEDGE_DIR", tmp_path)
    store.save_knowledge("notes/small.md", "tiny body", title="Small")

    out = do_read_knowledge("notes/small.md")
    # save_knowledge normalizes a trailing newline onto the body.
    assert out["body"].strip() == "tiny body"
    assert out["total_chars"] == len(out["body"])
    assert out["has_more"] is False
    assert out["next_offset"] is None


def test_read_knowledge_missing_path_errors(tmp_path, monkeypatch) -> None:
    import app.knowledge.store as store

    monkeypatch.setattr(store, "KNOWLEDGE_DIR", tmp_path)
    out = do_read_knowledge("nope.md")
    assert "error" in out


def test_read_knowledge_clamps_limit_to_max(tmp_path, monkeypatch) -> None:
    import app.knowledge.store as store
    from app.agent.tools.knowledge import READ_KNOWLEDGE_PAGE_MAX

    monkeypatch.setattr(store, "KNOWLEDGE_DIR", tmp_path)
    big = "x" * (READ_KNOWLEDGE_PAGE_MAX * 3)
    store.save_knowledge("notes/huge.md", big, title="Huge")

    # A huge `limit` must not dump the whole entry in one call.
    out = do_read_knowledge("notes/huge.md", limit=10_000_000)
    assert out["limit"] == READ_KNOWLEDGE_PAGE_MAX
    assert len(out["body"]) == READ_KNOWLEDGE_PAGE_MAX
    assert out["has_more"] is True
    assert out["next_offset"] == READ_KNOWLEDGE_PAGE_MAX
