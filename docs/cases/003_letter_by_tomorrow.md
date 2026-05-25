# 003 — Write letter by tomorrow

## Scenario

User says:

> I need to write a letter to my landlord by tomorrow.

## Expected user-visible behavior

- the assistant recognizes this as a **user todo with a deadline**, not something for the assistant to do.
- the assistant creates a task with `assignee="user"`, `due_at=tomorrow EOD` (or similar interpretation).
- the assistant's reply mentions the deadline: "Noted — letter to landlord, due tomorrow."
- TasksScreen shows a new row in the "Deadlines" section: title "Write letter to landlord", kind label "deadline", due_at displayed.
- No watchdog activity — `assignee=user` keeps the assistant out of it.
- User clicks task to open TaskDetailPage, can chat with the assistant about it ("help me draft", "what should I say"), or check the box when done.

## Expected row shape

```
title:          "Write letter to landlord"
description:    short context if any
assignee:       "user"
do_at:          null
due_at:         2026-05-01T17:00:00     (tomorrow EOD, agent picks)
interval_unit:  null
interval_count: null
```

Computed kind: `deadline`.

## Lifecycle

- Row created. State = `yours` (assignee=user).
- Watchdog ignores forever (assignee != assistant).
- User completes via UI checkbox → is_done=true, completed_at=now.

## Surprising / open questions

- the assistant must distinguish "I need to write a letter" (todo) from "write me a letter" (assistant job). Heuristic: subject = "I" → user; "you" / imperative → assistant. Codify in HOW_TASKS_WORK section if not clear from existing prompt.
- Does the assistant pick a default `due_at` time when user just says "by tomorrow" (no time)? Best guess: end-of-day in user's local tz. Should ask if ambiguous.
- The `result` auto-post mechanism is irrelevant here — `assignee=user` means the assistant never calls `complete_task` on this row. User checks the box from UI; no main-chat post.
