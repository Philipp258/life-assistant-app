# 13 — Main chat context pressure

**Goal.** Check that a long main-chat session is compacted before it
turns into a user-visible context-window failure.

**Persona.** The single operator having a detailed back-and-forth in the
main chat and expecting the assistant to stay usable as the conversation
grows.

**Release-test setup.** Do not try to hit the provider's real maximum
context. On the throwaway VPS, temporarily lower the app's compaction
threshold through `/etc/life-assistant/life-assistant.env`, then restart
the service. Use a small but nonzero threshold and a short recent tail,
for example `COMPACTION_TRIGGER_TOKENS=1200` and
`COMPACTION_KEEP_GROUPS=2`. This is test instrumentation, not a
user-facing setup step.

**What to try.** In main chat, create enough ordinary conversation to
cross the lowered threshold without dumping huge random text. Use a few
short paragraphs per turn, include several memorable details spread
across older and newer turns, and then ask a follow-up that depends on
both recent context and one older detail.

**Done when.** The chat continues without a context-limit error, lost
stream, or service crash. The assistant can use the recent conversation
normally and either remembers the older detail through the compacted
summary or gives a graceful uncertainty instead of failing. If you use
server-side evidence, keep it read-only and confirm that the main
session compacted older messages rather than carrying the full oversized
history into every turn.

**Rate.** Use judgment. Note whether the compaction threshold setup was
straightforward, whether the user experience stayed coherent during the
compaction turn, and whether any error messaging or latency would worry
a normal operator.
