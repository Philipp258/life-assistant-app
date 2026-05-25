# 001 — Remind me Saturday: groceries

## Scenario

User says in main chat (Friday afternoon):

> Remind me Saturday morning to get groceries.

## Expected user-visible behavior

- the assistant replies briefly, e.g. "Will do — reminder set for Saturday 9am."
- TasksScreen shows a new row: title "Reminder: groceries", kind label "scheduled job", do_at = Sat 09:00.
- Saturday 9am: a new the assistant message appears in the **main chat** with the reminder content (e.g. "Reminder: get groceries"). Task moves to Done section in the task list.

## Expected row shape

```
title:          "Reminder: groceries"   (or similar, agent's choice)
description:    null or short context
assignee:       "assistant"
do_at:          2026-05-02T09:00:00     (Saturday 09:00 in user's local tz)
due_at:         null
interval_unit:  null
interval_count: null
```

Computed kind: `scheduled-job`.

## Lifecycle

- Friday afternoon → row created. State = `up_next` (do_at in future).
- Watchdog ignores until do_at <= now.
- Saturday 09:00 → watchdog wakes the task's chat session.
- Empty chat → bootstrap synthetic prompt fires.
- Agent calls `complete_task(handoff="Reminder: get groceries")`.
- Foreground coordinator decides whether to post the reminder into main chat; for this case it should.
- Task is_done = true; completed_at set.

## Surprising / open questions

- Should the assistant's reply on creation Friday afternoon mention the time it will fire? (Yes — confirms the user got what they asked for.)
- What timezone? Today the runner uses UTC for `do_at` comparisons; user input must be parsed to UTC. Open: how the assistant parses "Saturday morning" — does it ask for a precise time, default to 9am, use core memory preferences?
- If user is offline / app closed Saturday 9am, when does the reminder fire? Today: as soon as app + watchdog are up and `do_at <= now`. No backlog suppression — late reminder still fires.
