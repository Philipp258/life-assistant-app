"""Voice-mode response style — issue #151.

Voice mode is now a field on the `input` message the client sends over
the channel (`{"type":"input", ..., "voice": true}`), threaded through
`runner.set_pending_voice` → `run_session_turn` →
`AgentDeps(voice_mode=...)` → `build_system_prompt`. When on, the
backend appends a compact spoken-style marker at the END of the
assistant's system prompt. The marker must:

- Reach the model's first SystemPromptPart on voice turns.
- Stay at the tail so the cached prefix (intro + memory + tree + skills)
  is byte-identical across voice/non-voice turns.
- Be absent entirely when the flag is false/omitted.
- Never leak into persisted chat history — voice mode is per-turn.
"""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    SystemPromptPart,
    TextPart,
)
from pydantic_ai.models.function import AgentInfo

from app.agent import VOICE_MODE_PROMPT, build_system_prompt
from app.chat.models import Message
from tests._ws import ws_turn


def _run_chat_turn(client, *, voice: bool | None) -> list[list[ModelMessage]]:
    """One chat turn over the channel, capturing every `messages` list
    the model saw."""
    main_id = client.get("/api/chat/main").json()["session_id"]
    captured: list[list[ModelMessage]] = []

    def handler(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        captured.append(list(messages))
        return ModelResponse(parts=[TextPart(content="ok")])

    ws_turn(
        client,
        session_id=main_id,
        text="what's the weather",
        handler=handler,
        voice=voice,
    )
    return captured


def _system_prompt_text(messages: list[ModelMessage]) -> str:
    chunks: list[str] = []
    for m in messages:
        parts = getattr(m, "parts", None) or []
        for p in parts:
            if isinstance(p, SystemPromptPart) and isinstance(p.content, str):
                chunks.append(p.content)
    return "\n".join(chunks)


def test_voice_flag_appends_marker_to_system_prompt(client):
    """Voice on → marker present at the tail of the system prompt.

    `replace_existing=True` on the adapter's ReinjectSystemPrompt
    capability strips synthetic SystemPromptParts handed in via
    `message_history`, so the voice marker has to come from the agent's
    own system prompt — which is exactly what `voice_mode` toggles.
    """
    captured = _run_chat_turn(client, voice=True)
    assert len(captured) >= 1, "model was never invoked"
    text = _system_prompt_text(captured[0])
    assert VOICE_MODE_PROMPT in text
    assert text.rstrip().endswith(VOICE_MODE_PROMPT.rstrip())


def test_no_voice_flag_means_no_marker(client):
    captured = _run_chat_turn(client, voice=None)
    assert len(captured) >= 1
    assert VOICE_MODE_PROMPT not in _system_prompt_text(captured[0])


def test_voice_flag_false_does_not_inject(client):
    captured = _run_chat_turn(client, voice=False)
    assert VOICE_MODE_PROMPT not in _system_prompt_text(captured[0])


def test_voice_mode_flag_is_per_turn_not_sticky(client):
    """A voice turn followed by a non-voice turn must produce a clean
    prompt — the flag never sticks to a session."""
    voice_captured = _run_chat_turn(client, voice=True)
    assert VOICE_MODE_PROMPT in _system_prompt_text(voice_captured[0])

    normal_captured = _run_chat_turn(client, voice=None)
    assert VOICE_MODE_PROMPT not in _system_prompt_text(normal_captured[0])


def test_persisted_user_prompt_does_not_include_voice_marker(client, _test_db):
    """The persisted user/assistant content must stay clean — the marker
    travels via the (server-regenerated) system prompt only."""
    Session = _test_db
    main_id = client.get("/api/chat/main").json()["session_id"]

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="spoken-friendly reply")])

    ws_turn(client, session_id=main_id, text="say hi", handler=handler, voice=True)

    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == main_id).order_by(Message.id).all()

    for row in rows:
        parts = (row.parts_json or {}).get("parts") or []
        for p in parts:
            if not isinstance(p, dict):
                continue
            if p.get("part_kind") in {"user-prompt", "text"}:
                content = p.get("content")
                if isinstance(content, str):
                    assert VOICE_MODE_PROMPT not in content, (
                        "voice-mode marker leaked into user prompt or assistant "
                        f"text: row.kind={row.kind} part={p!r}"
                    )


def test_build_system_prompt_cache_prefix_is_stable(_test_db):
    """Direct unit test on the builder: voice on/off must share the
    longest possible identical prefix so prompt-cache prefixes hit."""
    base = build_system_prompt(None, voice_mode=False)
    voiced = build_system_prompt(None, voice_mode=True)

    assert base != voiced
    assert voiced.startswith(base), "voice-mode marker must be appended after the stable portion"
    assert voiced.rstrip().endswith(VOICE_MODE_PROMPT.rstrip())


def test_voice_mode_prompt_mentions_spoken_style():
    text = VOICE_MODE_PROMPT.lower()
    assert "voice" in text
    assert any(kw in text for kw in ("spoken", "concise", "conversational"))
