# 004 — Every morning send me a recipe

## Scenario

User says:

> Every morning at 8am, send me a recipe idea.

## Expected user-visible behavior

- the assistant creates a recurring task: `assignee=assistant`, `do_at=tomorrow 08:00`, `interval_unit="day"`, `interval_count=1`.
- the assistant's reply confirms: "Routine set — recipe ideas every morning at 8am."
- TasksScreen "Routines" section shows the row.
- Each morning at 08:00:
  1. Watchdog wakes the current cycle's task.
  2. Agent generates a recipe idea.
  3. Agent calls `complete_task(handoff="Today's recipe: <name + 1-line summary>")`.
  4. Foreground coordinator posts the recipe into main chat.
  5. Service spawns next cycle: new task row + new chat session, do_at = today 08:00 + 1 day.
- User wakes up, sees recipe in main chat. Routine continues until user disables it.

## Expected row shape

```
title:          "Daily recipe idea"
description:    "Send a recipe each morning"
assignee:       "assistant"
do_at:          2026-05-01T08:00:00       (anchors first run)
due_at:         null
interval_unit:  "day"
interval_count: 1
```

Computed kind: `routine`.

## Lifecycle

- Initial row: state `up_next`.
- 08:00 → wake → agent generates recipe → completes with handoff.
- Foreground coordinator writes the recipe into main chat.
- Service `_spawn_next_recurrence` creates next row with do_at = previous_do_at + 1 day.

## Surprising / open questions

- **Routine spam confirmed acceptable** — user-locked decision. Trust agent to phrase concisely.
- **Recurrence anchors on prev_do_at** so cadence is preserved even if a cycle was woken late. Documented in HOW_TASKS_WORK.
- How does user **disable** a routine? Today: open task detail, mark is_done=true. That stops the current cycle, but recurrence still spawns the next one (because `_spawn_next_recurrence` fires on completion). Bug? Or expected? Open: probably need a "stop routine" affordance that ALSO suppresses the next-cycle spawn. Tracked as future work.
- New chat session every cycle = no continuity for "yesterday's recipe was X, do something different today". Agent can use `list_tasks(title="Daily recipe idea")` to find prior cycles' rows, then `list_chat_messages(prev_chat_session_id)` to read them. Documented in HOW_TASKS_WORK.
