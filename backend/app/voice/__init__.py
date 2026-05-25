"""Voice mode: provider-backed transcription + synthesis for the main chat.

Frontend records audio, posts it to ``/api/voice/transcribe``, and we
dispatch to whichever provider the user has configured (Z.AI, OpenRouter,
or Codex/ChatGPT). The text is submitted as a normal main-chat message,
and the assistant's reply is sent back to ``/api/voice/synthesize`` to
get a server-side TTS audio blob. The frontend falls back to the
browser's built-in ``speechSynthesis`` if the configured provider
doesn't expose a TTS endpoint (e.g. Z.AI today).
"""
