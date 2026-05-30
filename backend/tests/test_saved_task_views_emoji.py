from unittest.mock import MagicMock

from app.saved_task_views import emoji


def test_extract_one_emoji_picks_first_emoji_character():
    assert emoji.extract_one_emoji("Sure, I'd pick 🏠 for a home view.") == "🏠"


def test_extract_one_emoji_returns_none_when_absent():
    assert emoji.extract_one_emoji("no glyph here") is None


def test_pick_emoji_for_view_returns_extracted(monkeypatch):
    fake = MagicMock(return_value="✨")
    monkeypatch.setattr(emoji, "_run_llm", fake)
    out = emoji.pick_emoji_for_view(name="Mine", filters={"assignee": "user"})
    assert out == "✨"
    fake.assert_called_once()


def test_pick_emoji_for_view_returns_none_on_timeout(monkeypatch):
    def boom(_prompt: str, *, timeout_s: float) -> str:
        raise TimeoutError("nope")

    monkeypatch.setattr(emoji, "_run_llm", boom)
    assert emoji.pick_emoji_for_view(name="Home", filters={}) is None


def test_pick_emoji_for_view_returns_none_when_llm_returns_nothing_useful(monkeypatch):
    monkeypatch.setattr(emoji, "_run_llm", lambda *_a, **_k: "I'm not sure.")
    assert emoji.pick_emoji_for_view(name="x", filters={}) is None


def test_pick_emoji_for_view_returns_none_when_llm_hangs(monkeypatch):
    """`_run_llm` enforces a wall-clock timeout via ThreadPoolExecutor.

    Patches `get_agent` so the real `_run_llm` code path runs and we verify the
    timeout guard kicks in when the underlying agent blocks forever.
    """
    import time

    class FakeAgent:
        def run_sync(self, _prompt, **_kwargs):
            time.sleep(5)

            class R:
                output = "🏠"

            return R()

    monkeypatch.setattr(emoji, "get_agent", lambda: FakeAgent())
    out = emoji.pick_emoji_for_view(name="x", filters={}, timeout_s=0.05)
    assert out is None
