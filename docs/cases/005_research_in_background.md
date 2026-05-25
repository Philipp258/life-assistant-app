# 005 — Research best espresso machine, get back to me

## Scenario

User says:

> Research the best espresso machine under €500. Get back to me when you have a recommendation.

## Expected user-visible behavior

- the assistant creates: `assignee=assistant`, no do_at (start now), no interval, no due_at.
- the assistant's reply: "On it — I'll get back to you with options."
- TasksScreen "Jobs" section shows row, with live indicator (running ring) while the assistant works.
- the assistant runs autonomously inside the task chat. Calls `web_search("best espresso machine under 500 euro 2026 review")`, then `web_fetch` on 2-4 promising URLs to read the actual reviews. May take multiple wakes (watchdog re-wakes if it stays quiet > 60s but isn't done).
- When the assistant reaches a recommendation: it calls `complete_task(handoff="Espresso research: 3 picks under €500. Top: Breville Bambino. Want details?")`.
- The foreground coordinator decides how to post that handoff into main chat.
- Main chat receives the short handoff; detailed work stays in the task chat.
- User can open the task to read the full work-in-chat history.

## Expected row shape

```
title:          "Research best espresso machine under €500"
description:    "Recommend a top pick + alternatives"
assignee:       "assistant"
do_at:          null
due_at:         null
interval_unit:  null
interval_count: null
```

Computed kind: `job`.

## Lifecycle

- Row created → `assistant` + no do_at → state `running` immediately.
- runner.schedule_wake fires from create_task path.
- Agent works across multiple wakes if needed (each wake = one agent.run, can stretch many tool calls).
- Eventually `complete_task(handoff=...)` → foreground coordinator decides whether/how main chat receives the result.

## Surprising / open questions

- **Web tools shipped.** `web_search` (Brave) + `web_fetch` live. Real test now: does the assistant pick reasonable queries, follow 2-4 results deep, and synthesize — or does it dump raw search snippets and call it done? Quality of the result is the new failure mode, not "tool missing".
- **Token budget.** Each `web_fetch` returns up to 30k chars; 4 fetches can saturate the model context. the assistant needs to summarize as it goes (in-chat narration), not stockpile raw page text.
- **Sub-finding: should the assistant save its research to knowledge?** If user later asks "what was that espresso machine you found", the result message in main chat scrolls out. A `save_knowledge("research/espresso-2026.md", ...)` call as part of completion would persist it. Not currently in the prompt; revisit.
- The 60s watchdog re-wake on silence: if the assistant is genuinely thinking and stays quiet, it'll get re-woken. the assistant's HOW_TASKS_WORK section tells it to expect this and not pad. Worth checking in practice that re-wakes don't cause the assistant to repeat itself.
- The result message is the **handoff** — short summary. Detail lives in the task chat, accessible via TaskDetailPage. Don't dump full research into main chat.
