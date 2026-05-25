# 002 — Tell me how my train is if late tomorrow morning

## Scenario

User says (today, evening):

> Tell me tomorrow morning how my train is, but only if it's late.

## Expected user-visible behavior

- the assistant confirms: "Got it — I'll check tomorrow at 7am, and only message if it's late."
- TasksScreen: new "scheduled job" row.
- Tomorrow 07:00 (or whatever the assistant picked): watchdog wakes task. the assistant checks train status via `web_search` (e.g. "Deutsche Bahn ICE 728 status") and `web_fetch` on the top result, or fetches a known status page directly.
  - If late: the assistant completes with a handoff like "Your 8:14 train is delayed by 12 min"; the foreground coordinator posts it to main chat.
  - If on time: the assistant calls `complete_task(handoff="Train is on time; the user asked only to be interrupted if late.")`; the foreground coordinator should usually stay silent.

## Expected row shape

```
title:          "Check train status tomorrow morning"
description:    "Only message if late. Otherwise no need."
assignee:       "assistant"
do_at:          2026-05-01T07:00:00
due_at:         null
interval_unit:  null
interval_count: null
```

Computed kind: `scheduled-job`.

## Lifecycle

- Now → row created, state `up_next`.
- Tomorrow 07:00 → watchdog wakes.
- Agent's TASK_PROMPT + HOW_TASKS_WORK + task description steers it: check status, decide whether to message.
- Agent calls `complete_task(handoff=...)`; the foreground coordinator decides whether the outcome is worth surfacing.

## Surprising / open questions

- **Web tools shipped.** `web_search` (Brave) + `web_fetch` are wired (`backend/app/agent/tools/web.py`). Agent can actually do this. Open: parsing real-time train data behind cookie/JS walls — `web_fetch` is no-JS. For DB/SBB/Trainline-style sites, agent may need to fall back to a public status text page. Worst case: the assistant messages "couldn't get a live status, here's the schedule page link".
- "Only if late" is a conditional that lives entirely in the prompt — no schema concept of conditions needed. Confirmed earlier in design discussion.
- Result-required-on-completion vs silent completion: case forces the question. For v1: agent must post something, even if it's "Train on time." Revisit if cases reveal this is annoying.
