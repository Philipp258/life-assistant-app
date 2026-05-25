"""Cache-Control headers for the SPA + PWA bundle. See issue #173.

The installed PWA was pinning a stale app shell because `index.html`
and `sw.js` were served without cache headers — browsers/WebViews fell
back to heuristic freshness and held on to them for a long time. These
tests lock in the headers that prevent that, plus the
long-lived-immutable headers for Vite-hashed `/assets/*`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def frontend_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # app.main checks SESSION_SECRET at import time; the conftest
    # `_test_db` fixture normally seeds this, but the cache-header
    # tests don't need a DB so they set it themselves.
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-not-for-prod")

    from app.config import settings as _settings

    monkeypatch.setattr(
        _settings, "session_secret", "test-session-secret-not-for-prod", raising=True
    )

    from app.main import mount_frontend

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><html><head><meta name="life-assistant-build-id" content="abc" />'
        "</head><body></body></html>",
        encoding="utf-8",
    )
    (dist / "sw.js").write_text("// sw", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    (dist / "assets" / "index-DEADBEEF.js").write_text("/* bundle */", encoding="utf-8")

    test_app = FastAPI()
    mount_frontend(test_app, dist)
    return TestClient(test_app)


def test_index_html_is_uncacheable(frontend_client: TestClient) -> None:
    r = frontend_client.get("/")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "no-cache" in cc
    assert "no-store" in cc


def test_explicit_index_html_is_uncacheable(frontend_client: TestClient) -> None:
    r = frontend_client.get("/index.html")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "no-cache" in cc


def test_service_worker_is_uncacheable(frontend_client: TestClient) -> None:
    r = frontend_client.get("/sw.js")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "no-cache" in cc
    assert "no-store" in cc


def test_manifest_is_uncacheable(frontend_client: TestClient) -> None:
    r = frontend_client.get("/manifest.webmanifest")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "no-cache" in cc
    assert r.headers["content-type"].startswith("application/manifest+json")


def test_hashed_assets_are_immutable(frontend_client: TestClient) -> None:
    r = frontend_client.get("/assets/index-DEADBEEF.js")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "immutable" in cc
    assert "max-age=31536000" in cc


def test_spa_fallback_for_unknown_path_returns_uncacheable_index(
    frontend_client: TestClient,
) -> None:
    r = frontend_client.get("/some/deep/spa/route")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/html")
    cc = r.headers.get("cache-control", "")
    assert "no-cache" in cc
