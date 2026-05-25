"""Tests for the openclaw-style raw shell / fs / web tools."""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from app.agent.tools import fs as fs_tools
from app.agent.tools import shell as shell_tools
from app.agent.tools import web as web_tools


# --------------------------------------------------------------------- shell


def test_bash_echo_roundtrip() -> None:
    out = shell_tools.do_bash("echo hello")
    assert out["exit_code"] == 0
    assert out["stdout"].strip() == "hello"
    assert out["stderr"] == ""
    assert out["timed_out"] is False
    assert out["truncated"] is False


def test_bash_non_zero_exit() -> None:
    out = shell_tools.do_bash("ls /no/such/path/here/i/hope")
    assert out["exit_code"] != 0
    assert out["stderr"] != ""
    assert out["timed_out"] is False


def test_bash_timeout() -> None:
    out = shell_tools.do_bash("sleep 5", timeout=1)
    assert out["timed_out"] is True
    assert out["exit_code"] is None


def test_bash_stdout_truncation() -> None:
    # Generate ~60k chars of "x" on stdout via python
    cmd = "python3 -c \"import sys; sys.stdout.write('x' * 60000)\""
    out = shell_tools.do_bash(cmd)
    assert out["truncated"] is True
    assert len(out["stdout"]) == shell_tools.MAX_OUTPUT_CHARS


def test_bash_cwd_is_repo_root() -> None:
    out = shell_tools.do_bash("pwd")
    assert out["exit_code"] == 0
    assert out["stdout"].strip() == str(shell_tools.REPO_ROOT)


def test_bash_env_passthrough() -> None:
    out = shell_tools.do_bash("printenv PATH")
    assert out["exit_code"] == 0
    assert out["stdout"].strip() != ""


# ------------------------------------------------------------------------ fs


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Repoint fs_tools.REPO_ROOT at a tmp dir for relative-path resolution."""
    monkeypatch.setattr(fs_tools, "REPO_ROOT", tmp_path, raising=True)
    return tmp_path


def test_read_file_line_range(fake_repo: Path) -> None:
    target = fake_repo / "lines.txt"
    target.write_text("\n".join(f"line{i}" for i in range(1, 101)))

    out = fs_tools.do_read_file("lines.txt", offset=9, limit=5)
    assert "error" not in out
    assert out["total_lines"] == 100
    rendered = out["lines"].splitlines()
    assert len(rendered) == 5
    assert rendered[0].endswith("\tline10")
    assert rendered[-1].endswith("\tline14")
    assert out["truncated"] is True


def test_read_file_absolute_path(fake_repo: Path) -> None:
    target = fake_repo / "abs.txt"
    target.write_text("hi")
    out = fs_tools.do_read_file(str(target))
    assert "error" not in out
    assert "hi" in out["lines"]


def test_read_file_binary_rejected(fake_repo: Path) -> None:
    target = fake_repo / "blob.bin"
    target.write_bytes(b"hello\x00world")
    out = fs_tools.do_read_file("blob.bin")
    assert "error" in out
    assert "binary" in out["error"]


def test_read_file_missing(fake_repo: Path) -> None:
    out = fs_tools.do_read_file("nope.txt")
    assert "error" in out


def test_write_then_read(fake_repo: Path) -> None:
    out = fs_tools.do_write_file("a.txt", "alpha")
    assert out["ok"] is True
    out2 = fs_tools.do_read_file("a.txt")
    assert "alpha" in out2["lines"]


def test_write_auto_mkdir(fake_repo: Path) -> None:
    out = fs_tools.do_write_file("a/b/c.txt", "deep")
    assert out["ok"] is True
    assert (fake_repo / "a/b/c.txt").read_text() == "deep"


def test_edit_file_happy(fake_repo: Path) -> None:
    target = fake_repo / "e.txt"
    target.write_text("foo bar baz")
    out = fs_tools.do_edit_file("e.txt", "bar", "qux")
    assert out["ok"] is True
    assert target.read_text() == "foo qux baz"


def test_edit_file_not_unique(fake_repo: Path) -> None:
    target = fake_repo / "e.txt"
    target.write_text("dup dup")
    out = fs_tools.do_edit_file("e.txt", "dup", "X")
    assert "error" in out
    assert "matches 2" in out["error"]
    assert target.read_text() == "dup dup"


def test_edit_file_replace_all(fake_repo: Path) -> None:
    target = fake_repo / "e.txt"
    target.write_text("dup dup dup")
    out = fs_tools.do_edit_file("e.txt", "dup", "X", replace_all=True)
    assert out["ok"] is True
    assert out["replacements"] == 3
    assert target.read_text() == "X X X"


def test_edit_file_not_found(fake_repo: Path) -> None:
    target = fake_repo / "e.txt"
    target.write_text("foo")
    out = fs_tools.do_edit_file("e.txt", "missing", "x")
    assert "error" in out
    assert target.read_text() == "foo"


def test_glob_files_sorted_by_mtime(fake_repo: Path) -> None:
    import os
    import time

    older = fake_repo / "old.py"
    newer = fake_repo / "new.py"
    older.write_text("a")
    time.sleep(0.05)
    newer.write_text("b")
    # Force monotonic mtimes in case the FS coalesces.
    os.utime(older, (1_000_000_000, 1_000_000_000))
    os.utime(newer, (2_000_000_000, 2_000_000_000))

    out = fs_tools.do_glob_files("*.py")
    assert "error" not in out
    assert len(out["matches"]) == 2
    assert out["matches"][0].endswith("new.py")
    assert out["matches"][1].endswith("old.py")


def test_glob_files_rejects_absolute_pattern(fake_repo: Path) -> None:
    """Absolute glob patterns are ambiguous (does `/x/**/*.py` mean
    search the host fs or rebase under repo root?) and crash
    `Path.glob` on Python 3.11+. Reject up front with a clear error.
    """
    out = fs_tools.do_glob_files("/opt/life-assistant/.github/workflows/*.yml")
    assert "error" in out
    assert "relative" in out["error"].lower()
    assert "/opt/life-assistant" in out["error"]


def test_grep_with_rg(fake_repo: Path) -> None:
    if shutil.which("rg") is None:
        pytest.skip("rg not installed")
    target = fake_repo / "grep.txt"
    target.write_text("alpha\nneedle here\nbeta\n")
    out = fs_tools.do_grep("needle", path=str(fake_repo))
    assert "error" not in out
    assert any("needle" in m["text"] and m["line"] == 2 for m in out["matches"])


def test_grep_python_fallback(fake_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = fake_repo / "grep.txt"
    target.write_text("alpha\nneedle here\nbeta\n")
    monkeypatch.setattr(fs_tools.shutil, "which", lambda _name: None, raising=True)
    out = fs_tools.do_grep("needle", path=str(fake_repo))
    assert "error" not in out
    assert len(out["matches"]) == 1
    assert out["matches"][0]["line"] == 2
    assert out["matches"][0]["text"] == "needle here"


# ----------------------------------------------------------------------- web


class _StubResponse:
    def __init__(self, *, text: str, status: int = 200, content_type: str = "text/plain") -> None:
        self.text = text
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.url = "https://example.test/"


def test_web_fetch_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        web_tools.httpx,
        "get",
        lambda url, follow_redirects, timeout: _StubResponse(text="hello body"),
        raising=True,
    )
    out = web_tools.do_web_fetch("https://example.test/")
    assert out["status"] == 200
    assert out["body"] == "hello body"
    assert out["truncated"] is False


def test_web_fetch_html_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        "<html><head><style>x{}</style></head>"
        "<body><h1>Hi</h1><script>alert(1)</script>"
        "<p>p&amp;q</p></body></html>"
    )
    monkeypatch.setattr(
        web_tools.httpx,
        "get",
        lambda url, follow_redirects, timeout: _StubResponse(
            text=html, content_type="text/html; charset=utf-8"
        ),
        raising=True,
    )
    out = web_tools.do_web_fetch("https://example.test/")
    assert "<" not in out["body"]
    assert "alert" not in out["body"]
    assert "Hi" in out["body"]
    assert "p&q" in out["body"]


def test_web_fetch_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    big = "x" * (web_tools.MAX_BODY_CHARS + 5_000)
    monkeypatch.setattr(
        web_tools.httpx,
        "get",
        lambda url, follow_redirects, timeout: _StubResponse(text=big),
        raising=True,
    )
    out = web_tools.do_web_fetch("https://example.test/")
    assert out["truncated"] is True
    assert len(out["body"]) == web_tools.MAX_BODY_CHARS


def test_web_fetch_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        web_tools.httpx,
        "get",
        lambda url, follow_redirects, timeout: _StubResponse(text="nope", status=404),
        raising=True,
    )
    out = web_tools.do_web_fetch("https://example.test/")
    assert out["status"] == 404
    assert "error" not in out


def test_web_fetch_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_kw):
        raise httpx.ConnectError("dns fail")

    monkeypatch.setattr(web_tools.httpx, "get", boom, raising=True)
    out = web_tools.do_web_fetch("https://nope.invalid/")
    assert "error" in out
    assert "dns fail" in out["error"]


# -------------------------------------------------------------- web_search


class _StubJsonResponse:
    def __init__(self, *, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.text = "stub"

    def json(self) -> dict:
        return self._payload


def test_web_search_no_key(_test_db) -> None:
    out = web_tools.do_web_search("anything")
    assert "error" in out
    assert "Brave API key not configured" in out["error"]


def test_web_search_ok(_test_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import service as settings_service

    with _test_db() as db:
        settings_service.set_runtime_setting(db, key="brave_api_key", value="test-key")
    payload = {
        "web": {
            "results": [
                {
                    "title": "Nix",
                    "url": "https://example.test/nix",
                    "description": "personal assistant",
                },
                {
                    "title": "Desk",
                    "url": "https://example.test/desk",
                    "description": "furniture",
                },
            ]
        }
    }

    captured: dict = {}

    def fake_get(url, params, headers, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _StubJsonResponse(payload=payload)

    monkeypatch.setattr(web_tools.httpx, "get", fake_get, raising=True)
    out = web_tools.do_web_search("nix", count=2)
    assert "error" not in out
    assert out["count"] == 2
    assert out["results"][0]["title"] == "Nix"
    assert out["results"][0]["snippet"] == "personal assistant"
    assert captured["params"]["q"] == "nix"
    assert captured["params"]["count"] == 2
    assert captured["headers"]["X-Subscription-Token"] == "test-key"


def test_web_search_count_clamp(_test_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import service as settings_service

    with _test_db() as db:
        settings_service.set_runtime_setting(db, key="brave_api_key", value="test-key")

    captured: dict = {}

    def fake_get(url, params, headers, timeout):
        captured["params"] = params
        return _StubJsonResponse(payload={"web": {"results": []}})

    monkeypatch.setattr(web_tools.httpx, "get", fake_get, raising=True)
    web_tools.do_web_search("x", count=999)
    assert captured["params"]["count"] == web_tools.SEARCH_MAX_COUNT
    web_tools.do_web_search("x", count=0)
    assert captured["params"]["count"] == 1


def test_web_search_non_200(_test_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import service as settings_service

    with _test_db() as db:
        settings_service.set_runtime_setting(db, key="brave_api_key", value="test-key")
    monkeypatch.setattr(
        web_tools.httpx,
        "get",
        lambda url, params, headers, timeout: _StubJsonResponse(payload={}, status=429),
        raising=True,
    )
    out = web_tools.do_web_search("rate limit me")
    assert "error" in out
    assert "429" in out["error"]


def test_web_search_http_error(_test_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import service as settings_service

    with _test_db() as db:
        settings_service.set_runtime_setting(db, key="brave_api_key", value="test-key")

    def boom(*_a, **_kw):
        raise httpx.ConnectError("dns fail")

    monkeypatch.setattr(web_tools.httpx, "get", boom, raising=True)
    out = web_tools.do_web_search("x")
    assert "error" in out
    assert "dns fail" in out["error"]
