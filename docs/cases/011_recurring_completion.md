# 011 — Recurring completion spawns next instance

## Scenario

User has a routine (e.g. case 004 — daily recipe). One cycle completes. Verify:
1. Current row is_done=true, completed_at set.
2. New row is created with do_at = previous_do_at + interval.
3. New row has its own fresh ChatSession (no carryover from previous cycle).
4. User-facing summary from the completing cycle is handed to the foreground coordinator.

## Expected user-visible behavior

- Completing cycle → foreground coordinator may post the assistant summary (e.g. "Today's recipe: shakshuka") to main chat.
- TasksScreen Done section gets the completed cycle.
- Routines section now shows the new cycle (next instance).
- The new cycle waits until its do_at fires.

## Expected row shapes

**Cycle N (just completed):**
```
is_done:        true
completed_at:   <now>
chat_session_id: <previous chat>
```

**Cycle N+1 (just spawned):**
```
title:          same as N
description:    same as N
assignee:       same as N (assistant)
do_at:          N.do_at + interval (or now + interval if N had no do_at)
due_at:         null   (NOT carried — recurrence resets)
interval_unit:  same as N
interval_count: same as N
chat_session_id: <new fresh session>
is_done:        false
```

## Lifecycle

- complete_task on N → update_task sets is_done=true → just_completed=true.
- _spawn_next_recurrence creates N+1 with fresh ChatSession.
- If the result is worth surfacing, the agent includes it in `complete_task(handoff=...)`; the foreground coordinator decides what to post.
- N+1 waits for its do_at; watchdog wakes when due.

## Surprising / open questions

- `due_at` is **not** carried across recurrence cycles. Correct? Probably — routines rarely have meaningful deadlines per cycle. If user sets due_at on a recurring row (weird), it gets reset on each spawn. Documented behavior.
- Anchoring on prev_do_at preserves cadence even if a cycle fired late (from `_next_do_at` in service.py).
- The fresh ChatSession means cycle-N+1 has no scrollback of cycle-N. Agent must use `list_tasks(title=...)` to find prior cycles + `list_chat_messages(prior_chat_session_id)` to read them.
