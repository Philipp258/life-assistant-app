# 06 — Background task

Status: green

What I tried: asked the assistant to find three well-reviewed espresso machines under €500 in the background and summarize trade-offs.

What worked: the assistant created `Find three espresso machines under €500`, reported that it was working in the background, ran the task, showed task activity with `web_search`, many `web_fetch` calls, and `complete_task`, then handed the result back into main chat. The final answer compared Sage/Breville Bambino, Gaggia Classic E24, and De'Longhi Dedica/Dedica Arte.

Friction: none blocking. The task details were useful and inspectable.

Rating: autonomous background work and handoff worked well.
