# 05 — Reminder fires

Status: green

What I tried: asked for a release-test reminder in three minutes: stretch shoulders.

What worked: the assistant created `Remind Philipp to stretch shoulders` for `Today 22:52`. Shortly after the due time, main chat received `Reminder: stretch your shoulders.` The task moved out of the open list into Done archive, where it was visible as completed. The DB showed `completed_at=2026-05-28T20:52:55.660077` and `is_done=True`.

Friction: the first poll at the due minute showed the task not completed yet; it fired after another short wait. That is acceptable for a scheduler.

Rating: end-to-end reminder firing worked and surfaced in main chat.
