# 010 — User edits running task

## Scenario

the assistant is mid-job (assignee=assistant). User opens TaskDetailPage and:
- Edits the title from "Research espresso machines" to "Research espresso machines (under €300, not €500)".
- Or edits description to add new constraint.
- Or changes do_at to "now" (was scheduled for later).

## Expected user-visible behavior

- Edit applies immediately (PATCH /tasks/{id} unguarded — confirmed by code, v1 by-design).
- the assistant, on next wake (could be already wide-awake or next 60s tick), re-reads task from DB.
- Agent's TASK_PROMPT injects **fresh** title + description into system prompt every wake.
- Agent should notice the change and adjust.

## Expected row shape

After edit: same row, mutated fields. updated_at bumped. No spawned row, no completion side effects.

## Lifecycle

- PATCH lands → service.update_task applies fields.
- If do_at changed to past-now while assignee=assistant: watchdog picks up at next 5s tick (already eligible).
- Mid-turn agent.run isn't interrupted; the next wake reads fresh data.

## Surprising / open questions

- **No mid-turn cancellation.** If Life Assistant is already partway through a thought (e.g. drafting a recommendation for the €500 case), the in-flight wake completes its current agent.run. Edits land but the assistant's current message is based on stale title. Acceptable for v1 — wake gaps are short.
- **HOW_TASKS_WORK section explicitly tells the agent**: "User can edit task fields mid-run. Re-read fresh task data on each wake; don't assume description is static." Verify in practice that agent actually adjusts.
- Open: should we surface a "task changed since you started" hint to the agent? Maybe inject a synthetic system message on wake when updated_at > previous wake. Not in v1.
