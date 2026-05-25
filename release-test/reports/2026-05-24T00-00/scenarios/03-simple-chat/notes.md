# 03 — Simple chat

**Status:** red
**Severity:** blocker
**Reason:** blocked by 02 (Codex API rejects every model name tried
for this `prolite`-plan ChatGPT account, so the chat backend never
produces a reply).

The chat UI itself rendered, accepted input, and dispatched the
message. The failure is entirely in the model call. See
`../02-first-login-and-onboarding/notes.md` for detail.

The only signal collected from this scenario beyond what 02 found:

- The error surfaced in chat is a generic "Something went wrong
  handling that — your message wasn't answered. Please try again."
  toast. The actual 400 model-rejection body never reaches the user.
  When the underlying error is "Codex doesn't allow this model on
  your account", that diagnosis is one click to fix in the UI and
  zero clicks to discover from the chat — but only if the message is
  shown.
