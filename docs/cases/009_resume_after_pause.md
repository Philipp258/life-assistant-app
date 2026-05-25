# 009 — Resume after pause

## Scenario

the assistant is mid-job (assignee=assistant, running). Mid-loop, the assistant needs user input. It asks clearly in the task chat, then calls `reassign_task(assignee="user", handoff="Need your call: option A or B?")`. The foreground coordinator decides whether/how to ask in main chat. the user can answer from main chat; the main-chat agent can relay the answer into the task chat with `post_message_to_session`, then call `update_task(task_id, assignee="assistant")`. the assistant resumes.

## Expected user-visible behavior

1. the assistant running → posts a message in task chat asking for clarification.
2. the assistant calls `reassign_task('user', handoff=...)` — autonomous loop ends after this turn.
3. Main chat receives the question ("Need your call: A or B?").
4. TasksScreen: row moves from "Jobs" to a "Yours" / "Awaiting you" affordance. Open: do we section by-kind only (today's plan) or also surface "your action needed" specifically? **For v1, kind=job stays kind=job; only assignee changes.** UI may want a small "you" badge on the row when assignee=user but the task was originally an assistant-job.
5. User can answer in main chat, especially in voice mode. If the answer clearly belongs to this task, the main-chat agent posts a relayed note into the task chat and reassigns it to the assistant. User can still open the task chat for detail.
6. Reassigning user → assistant schedules the autonomous loop. The assistant resumes from the task chat with the relayed instruction in history.

## Expected row shape

```
title:          unchanged
description:    unchanged
assignee:       "assistant" → "user" → "assistant" (after resume)
do_at:          unchanged
due_at:         unchanged
interval_*:     null (this is a one-shot job)
```

Kind stays `job` throughout (computed from assignee=assistant or wouldn't be job anymore). When user-assigned mid-run, kind flips to `todo` since assignee=user.

## Lifecycle

- assistant → user via reassign_task: schedule_wake NOT fired (handed away). The lifecycle handoff is hidden context for the foreground coordinator, which may post to main chat or stay silent.
- user → assistant via `update_task(..., assignee="assistant")` from main chat, `reassign_task('assistant')` from task chat, or PATCH: schedule_wake fires from update_task path, autonomous loop resumes.

## Surprising / open questions

- **Kind flips when assignee flips.** A "job" handed to user becomes a "todo". Confusing? Or correct (it IS a todo for the user now)? Probably correct, but UI should show some sign of provenance ("the assistant handed this back").
- Resume mechanism today: user can reassign back via UI buttons, reply in task chat, or answer in main chat and let the main-chat agent relay/reassign. Worth checking UX clarity in practice.
- Edit-while-running guards out of scope (v1) — user could also change title/desc/dates while in this state. Not blocked.
