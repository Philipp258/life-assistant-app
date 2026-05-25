"""HTTP API for skills: list + read by name."""

from __future__ import annotations


def test_get_skills_lists_defaults(client):
    """Defaults under backend/defaults/skills/ are surfaced by GET /api/skills."""
    r = client.get("/api/skills")
    assert r.status_code == 200
    body = r.json()
    names = [s["name"] for s in body["skills"]]
    assert "add-skills" in names
    by_name = {s["name"]: s for s in body["skills"]}
    assert by_name["add-skills"]["source"] == "default"


def test_get_skill_by_name_returns_body(client):
    r = client.get("/api/skills/add-skills")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "add-skills"
    assert body["description"]
    assert "Add skills" in body["body"]
    assert body["source"] == "default"


def test_get_skill_404_for_unknown(client):
    r = client.get("/api/skills/does-not-exist")
    assert r.status_code == 404


def test_get_skill_400_on_traversal(client):
    # FastAPI routes `/skills/{name}` so `..` and `/foo` get URL-decoded
    # into the slug. Slug validation should reject them as 400 (or the
    # router rejects them outright with 404 before reaching us — both
    # are acceptable as long as nothing escapes data/skills/).
    for bad in ("..", "Foo-Bar", "-bad", "bad-", "with.dot"):
        r = client.get(f"/api/skills/{bad}")
        assert r.status_code in (400, 404)
