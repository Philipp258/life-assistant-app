"""Knowledge filesystem layer — path hardening + frontmatter round-trip.

These functions are reused by both the HTTP router and the agent tools,
so a regression here would let a hostile path slip through every surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def knowledge_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "knowledge"
    root.mkdir()
    import app.config as config_mod
    from app.knowledge import store as fs_mod

    monkeypatch.setattr(config_mod, "KNOWLEDGE_DIR", root, raising=True)
    monkeypatch.setattr(fs_mod, "KNOWLEDGE_DIR", root, raising=True)
    return root


def test_save_then_read_preserves_body_and_assigns_id(knowledge_root: Path):
    from app.knowledge import store as fs

    k = fs.save_knowledge("interests/bikes.md", "Steel frames.", title="Bikes")
    assert k.path == "interests/bikes.md"
    assert k.title == "Bikes"
    assert k.id  # uuid assigned

    read = fs.read_knowledge("interests/bikes.md")
    assert read.id == k.id
    assert read.title == "Bikes"
    assert "Steel frames." in read.body


def test_save_twice_preserves_id_and_created(knowledge_root: Path):
    from app.knowledge import store as fs

    a = fs.save_knowledge("a.md", "v1", title="A")
    b = fs.save_knowledge("a.md", "v2", title="A2")
    assert a.id == b.id
    assert a.created == b.created
    assert b.title == "A2"
    assert b.body.strip() == "v2"


def test_path_traversal_blocked(knowledge_root: Path):
    from app.knowledge import store as fs

    with pytest.raises(fs.KnowledgeError):
        fs.save_knowledge("../escape.md", "x")
    with pytest.raises(fs.KnowledgeError):
        fs.read_knowledge("../../etc/passwd")
    with pytest.raises(fs.KnowledgeError):
        fs.save_knowledge("/abs/path.md", "x")


def test_must_end_in_md(knowledge_root: Path):
    from app.knowledge import store as fs

    with pytest.raises(fs.KnowledgeError):
        fs.save_knowledge("foo.txt", "x")


def test_walk_tree_returns_titles(knowledge_root: Path):
    from app.knowledge import store as fs

    fs.save_knowledge("interests/bikes.md", "x", title="Bikes")
    fs.save_knowledge("interests/chess.md", "x", title="Chess")
    fs.save_knowledge("paris.md", "x", title="Paris trip")
    items = fs.walk_tree()
    paths = sorted(k.path for k in items)
    assert paths == ["interests/bikes.md", "interests/chess.md", "paris.md"]
    titles = {k.path: k.title for k in items}
    assert titles["interests/bikes.md"] == "Bikes"
    assert titles["paris.md"] == "Paris trip"


def test_move_preserves_id_and_bumps_updated(knowledge_root: Path):
    from app.knowledge import store as fs

    a = fs.save_knowledge("old.md", "body", title="Old")
    moved = fs.move_knowledge("old.md", "new/place.md")
    assert moved.path == "new/place.md"
    assert moved.id == a.id
    # `updated` is bumped (or at minimum equal — both timestamps to-the-second).
    assert moved.updated >= a.updated


def test_move_rejects_existing_destination(knowledge_root: Path):
    from app.knowledge import store as fs

    fs.save_knowledge("a.md", "x")
    fs.save_knowledge("b.md", "y")
    with pytest.raises(fs.KnowledgeError):
        fs.move_knowledge("a.md", "b.md")


def test_delete_folder_recursive(knowledge_root: Path):
    from app.knowledge import store as fs

    fs.save_knowledge("topic/a.md", "x")
    fs.save_knowledge("topic/sub/b.md", "y")
    assert (knowledge_root / "topic" / "sub" / "b.md").exists()
    fs.delete_folder("topic")
    assert not (knowledge_root / "topic").exists()


def test_delete_folder_refuses_root(knowledge_root: Path):
    from app.knowledge import store as fs

    fs.save_knowledge("a.md", "x")
    with pytest.raises(fs.KnowledgeError):
        fs.delete_folder("")


def test_render_tree_for_prompt_format(knowledge_root: Path):
    from app.knowledge import store as fs

    fs.save_knowledge("interests/bikes.md", "x", title="Bikes")
    fs.save_knowledge("paris.md", "x", title="Paris trip")
    out = fs.render_tree_for_prompt(fs.walk_tree())
    assert "- interests/bikes.md — Bikes" in out
    assert "- paris.md — Paris trip" in out


def test_frontmatter_with_special_chars(knowledge_root: Path):
    from app.knowledge import store as fs

    title = 'Title with "quotes" and: colons'
    fs.save_knowledge("weird.md", "body", title=title)
    read = fs.read_knowledge("weird.md")
    assert read.title == title


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@pytest.fixture
def populated(knowledge_root: Path):
    from app.knowledge import store as fs

    fs.save_knowledge("interests/bikes.md", "Steel frames and gravel rides.", title="Bikes")
    fs.save_knowledge("notes/random.md", "I love my bike commute every morning.", title="Random")
    fs.save_knowledge("finance/taxes.md", "Quarterly estimate.", title="Q1")
    return fs


def test_search_title_outranks_body_only(populated):
    hits = populated.search("bike")
    assert [h.path for h in hits] == ["interests/bikes.md", "notes/random.md"]
    # Title + path + title-prefix bonus beats a lone body hit.
    assert hits[0].score > hits[1].score
    assert hits[0].matched_in == ["title", "path"]
    assert hits[1].matched_in == ["body"]


def test_search_is_and_across_tokens(populated):
    # "gravel" is only in bikes.md's body; "bike" is in its title/path.
    hits = populated.search("gravel bike")
    assert [h.path for h in hits] == ["interests/bikes.md"]
    # A token present in no entry excludes everything.
    assert populated.search("gravel zzz") == []


def test_search_is_case_insensitive(populated):
    assert [h.path for h in populated.search("BIKES")] == ["interests/bikes.md"]


def test_search_matches_path_only(populated):
    hits = populated.search("taxes")
    assert [h.path for h in hits] == ["finance/taxes.md"]
    assert hits[0].matched_in == ["path"]
    assert hits[0].snippet is None


def test_search_snippet_only_for_body_match(populated):
    body_hit = populated.search("gravel")[0]
    assert body_hit.snippet is not None
    assert "gravel" in body_hit.snippet.lower()

    title_hit = next(h for h in populated.search("bike") if h.path.endswith("bikes.md"))
    assert title_hit.snippet is None


def test_search_snippet_window_has_ellipsis(knowledge_root: Path):
    from app.knowledge import store as fs

    long = "x " * 200 + "needle" + " y" * 200
    fs.save_knowledge("big.md", long, title="Big")
    hit = fs.search("needle")[0]
    assert hit.snippet is not None
    assert hit.snippet.startswith("…") and hit.snippet.endswith("…")
    assert "needle" in hit.snippet


def test_search_blank_and_no_match(populated):
    assert populated.search("") == []
    assert populated.search("   ") == []
    assert populated.search("xylophone") == []


def _write_entry(root: Path, rel: str, *, title: str, body: str, updated: str) -> None:
    """Write a knowledge file with exact frontmatter — lets a test pin
    `updated` (save_knowledge stamps now() to-the-second, which collides
    across fast saves and can't exercise the tiebreak)."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f'---\nid: "id-{rel}"\ntitle: "{title}"\n'
        f'created: "2026-01-01T00:00:00Z"\nupdated: "{updated}"\n---\n{body}\n',
        encoding="utf-8",
    )


def test_search_updated_then_title_break_score_ties(knowledge_root: Path):
    from app.knowledge import store as fs

    # Same title/body/no-path-match → identical score. Filenames carry no
    # query token so `path` doesn't perturb the score.
    _write_entry(knowledge_root, "a.md", title="Report", body="x", updated="2026-05-01T00:00:00Z")
    _write_entry(knowledge_root, "b.md", title="Report", body="x", updated="2026-05-10T00:00:00Z")
    paths = [h.path for h in fs.search("report")]
    # Equal score → more recently updated first.
    assert paths == ["b.md", "a.md"]

    # Equal score AND equal updated → title ascending.
    _write_entry(knowledge_root, "c.md", title="Report Z", body="x", updated="2026-06-01T00:00:00Z")
    _write_entry(knowledge_root, "d.md", title="Report A", body="x", updated="2026-06-01T00:00:00Z")
    res = fs.search("report")
    same = [h for h in res if h.updated == "2026-06-01T00:00:00Z"]
    assert [h.path for h in same] == ["d.md", "c.md"]  # "Report A" < "Report Z"


def test_search_title_prefix_bonus_isolated(knowledge_root: Path):
    from app.knowledge import store as fs

    # "rep" starts "Report" (+TITLE_W +PREFIX_BONUS) but only sits inside
    # "Prep work" (+TITLE_W, no prefix). Filenames hold no "rep".
    _write_entry(knowledge_root, "x1.md", title="Report", body="z", updated="2026-05-01T00:00:00Z")
    _write_entry(
        knowledge_root, "x2.md", title="Prep work", body="z", updated="2026-05-09T00:00:00Z"
    )
    res = fs.search("rep")
    assert [h.path for h in res] == ["x1.md", "x2.md"]  # prefix wins despite older
    by_path = {h.path: h.score for h in res}
    assert by_path["x1.md"] - by_path["x2.md"] == fs._TITLE_PREFIX_BONUS
