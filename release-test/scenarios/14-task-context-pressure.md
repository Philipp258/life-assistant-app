# 14 — Task context pressure

**Goal.** Check that an assistant-owned task can keep working when its
task chat grows large enough to require compaction or context recovery.

**Persona.** The single operator delegating a detailed background task
with enough notes, corrections, and intermediate output that the task's
private chat becomes long.

**Release-test setup.** Reuse the lowered compaction settings from the
main-chat context-pressure scenario. If they were not set yet, apply the
same temporary `COMPACTION_TRIGGER_TOKENS` and
`COMPACTION_KEEP_GROUPS` overrides in
`/etc/life-assistant/life-assistant.env`, then restart the service.

**What to try.** Create an assistant-owned task with a detailed but
bounded brief. Include several memorable constraints and ask the task to
produce a result after reasoning over them. Add enough task-chat
interaction or task detail to cross the lowered threshold without using
provider-sized filler. Prefer realistic notes, edits, or extra context
over meaningless repeated text.

**Done when.** The task does not pause or fail because of a context-window
error. It either completes, waits for user input, or reschedules itself
for a clear reason, and the task details/chat remain understandable. If
you use server-side evidence, keep it read-only and confirm that the
task session compacted or recovered instead of persisting an unbounded
tool/chat payload. Restore normal compaction settings before continuing
to open exploration by removing the temporary overrides or returning
them to `COMPACTION_TRIGGER_TOKENS=80000` and
`COMPACTION_KEEP_GROUPS=8`, then restarting the service.

**Rate.** Use judgment. Note whether task progress stayed visible,
whether any context recovery was understandable from the task details,
and whether the result suggests task chats are protected as well as main
chat.
