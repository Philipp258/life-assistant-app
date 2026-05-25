# 008 — Weekly reflection (system routine)

## Scenario

System (not user) routine, seeded by migration `a8c2f1e94b03_seed_weekly_reflection.py`. Fires every Sunday at 8pm. the assistant reviews the week (lists tasks completed since last reflection, looks at chat highlights), writes a short reflection note into knowledge.

## Expected user-visible behavior

- Sunday 20:00: watchdog wakes the routine's task chat.
- the assistant reads recent activity (`list_tasks(since=last_reflection_completed_at)`), reads relevant chats (`list_chat_messages`), notes durable bits to knowledge via `save_knowledge`.
- the assistant calls `complete_task(handoff="Weekly reflection done — saved 2 notes. Top theme: X.")`.
- The foreground coordinator posts the summary to main chat if it is useful.
- Main chat receives the summary. Completing the routine spawns next cycle for next Sunday 20:00.

## Expected row shape

Already seeded. Recurring weekly. assignee=assistant. interval_unit=week, interval_count=1.

Computed kind: `routine`.

## Lifecycle

- Existing seed → recurrence per `_spawn_next_recurrence` → infinite loop on weekly cadence.
- Each cycle: fresh chat session, agent runs, completes with handoff, foreground coordinator may post result, next instance spawned.

## Surprising / open questions

- This case tests the **routine + recurrence + post-to-main + knowledge write** integration end-to-end. If anything breaks the chain, this routine is the canary.
- The reflection's prompt (description) currently lives in seed migration. Should migrate to a `data/system/routines/*.md` file in the future (roadmap item).
- Per-cycle context across recurrences: agent must `list_tasks(title="Weekly reflection")` to find prior reflections, then read prior chat history. Good test of cross-recurrence continuity.
