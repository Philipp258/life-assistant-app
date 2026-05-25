# 007 — Do these 5 things

## Scenario

User pastes or dictates a list:

> Do these 5 things: 1) book a haircut, 2) check the weather for Friday, 3) draft a 1-paragraph thank-you note to Sarah, 4) find a recipe for tagine, 5) remind me to call Mum on Sunday.

## Expected user-visible behavior

- the assistant creates **5 separate tasks**, NOT one task with sub-steps. Tasks are atomic — that's the rule.
- Mix of kinds:
  1. "Book a haircut" — assistant job (or user, if the assistant can't actually book — see Open).
  2. "Check Friday weather" — assistant scheduled-job (do_at=Friday morning) or job-now.
  3. "Draft thank-you to Sarah" — assistant job, work happens in task chat, `complete_task(handoff=...)` marks it done and gives the draft to the foreground coordinator.
  4. "Find tagine recipe" — assistant job.
  5. "Remind: call Mum Sunday" — assistant scheduled-job, do_at=Sunday morning.
- the assistant's reply: brief summary of what got created. "5 tasks queued — see your tasks list."
- TasksScreen shows 5 new rows in their respective sections (Jobs, Scheduled jobs).
- Each task runs / waits independently. Some complete fast (recipe lookup), some wait (Sunday reminder).

## Expected row shapes

5 rows, each scoped to one item. Recurrence = none for any of them. Mix of `do_at` set / not set, `assignee` mostly assistant.

## Lifecycle

- 5 rows created in one tool-batch (the assistant can call `create_task` 5 times in a single turn).
- Live-running ones start immediately (watchdog wakes).
- Scheduled ones wait until their `do_at`.
- Each assistant job completes individually with a handoff; the foreground coordinator posts user-facing outcomes to main chat when useful.

## Surprising / open questions

- **No batch create tool today.** the assistant calls `create_task` 5 times. That's fine — Pydantic AI tool loops support multiple calls per turn. Verify in practice.
- 5 main-chat posts when all complete = mild noise. User may want a "summary" mode. Not in v1 scope.
- Some items genuinely belong to user, not the assistant (e.g. "book a haircut" if the assistant has no booking tool). the assistant needs to be honest: "I can't book that, added to your todos."
- This is the strongest test of the kind-compute logic: 5 rows yielding 3+ different kind labels.
