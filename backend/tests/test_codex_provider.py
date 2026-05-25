"""Tests for app.agent.providers.codex.

Pin the streaming-coercion behavior: `_CodexResponsesModel.request` must
delegate to `request_stream` so we never send a non-streamed POST to
Codex's Responses endpoint, which rejects them with
`400 {"detail": "Stream must be set to true"}` on newer models.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agent.providers.codex import _CodexResponsesModel


class _FakeStream:
    """Minimal StreamedResponse stand-in: drain → empty, get() → sentinel."""

    def __init__(self, sentinel: Any) -> None:
        self._sentinel = sentinel
        self.drained = False

    def __aiter__(self):
        async def _gen():
            self.drained = True
            if False:  # pragma: no cover — empty stream
                yield None

        return _gen()

    def get(self) -> Any:
        return self._sentinel


def test_request_delegates_to_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """`request` must enter `request_stream`, drain it, and return `stream.get()`."""
    sentinel = object()
    fake_stream = _FakeStream(sentinel)

    @asynccontextmanager
    async def fake_request_stream(self, messages, model_settings, model_request_parameters):
        yield fake_stream

    monkeypatch.setattr(_CodexResponsesModel, "request_stream", fake_request_stream)

    model = _CodexResponsesModel.__new__(_CodexResponsesModel)
    result = asyncio.run(
        model.request(
            messages=["msg"],
            model_settings=None,
            model_request_parameters=MagicMock(),
        )
    )

    assert result is sentinel
    assert fake_stream.drained, "request() must consume the stream before returning"
