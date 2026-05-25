# 04 — Schedule a Reminder

Status: green

What worked:
- Asked: car-repair appointment Thursday June 4, 2026 at 14:00; remind me the morning before at 08:00.
- Assistant replied: "I'll remind you Wednesday, June 3, 2026 at 08:00."
- Task list showed `Remind Phil about car-repair appointment`, `kind=scheduled-job`, `state=up_next`, `do_at=2026-06-03T08:00:00Z`.

Friction:
- The stored timestamp is UTC. The visible assistant confirmation did not mention timezone, so a non-UTC user may need clearer timezone handling in the UI.

Rating:
- Green. The task was created and easy to verify through `/api/tasks`.
