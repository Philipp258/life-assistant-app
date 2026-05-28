# 05 — Reminder fires

**Goal.** Schedule an artificial reminder for a few minutes from now
and observe what actually happens when it becomes due.

**Persona.** A tester intentionally using a short-delay reminder to
exercise the firing path, even though a real user would usually set a
reminder farther in the future.

**Done when.** The reminder has either fired or clearly failed to fire
within a reasonable waiting window. When it fires, confirm where the
result appears: main chat, task list, task details, notifications, or
some other visible place.

**Rate.** Use judgment. Note whether the outcome was easy to notice,
whether task details explain what happened, and whether a user would
understand that the reminder had actually been handled.
