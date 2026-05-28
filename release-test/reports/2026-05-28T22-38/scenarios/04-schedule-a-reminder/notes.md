# 04 — Schedule a reminder

Status: yellow
Severity: friction

What I tried: asked for a reminder for a car repair appointment on Thursday, June 4, 2026 at 15:00, with the reminder the morning before at 09:00.

What worked: the assistant created `Remind Philipp about car repair appointment`, and the stored task `do_at` was `2026-06-03T09:00:00`. The assistant's chat response correctly said Wednesday, June 3 at 09:00.

Friction: the task card and Tasks list displayed `3 Jun · 11:00`, two hours later than the requested/stored time. That makes the reminder look wrong even though the DB value is correct.

Rating: scheduling itself worked, but the UI time display is a serious trust issue for reminders.
