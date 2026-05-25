# 012 — Quick web lookup in main chat

## Scenario

User says in main chat:

> When does the next German federal election happen?

A short factual question the assistant doesn't have in core memory or knowledge.

## Expected user-visible behavior

- the assistant recognizes this needs current info, not memory.
- the assistant calls `web_search("next German federal election date")`.
- the assistant picks 1 promising result and calls `web_fetch(url)` for confirmation, OR — if the search snippet itself is unambiguous — answers from snippets alone.
- the assistant replies inline in main chat with the answer + a one-line citation (URL or source name).
- No task created. This is a chat-shaped question, not work.

## What the assistant should NOT do

- Spin up a task ("Spun this into a task: research election date") — over-engineering. Roadmap §2 "smart task-by-default" caveats: easy lookups answer inline.
- Dump raw `web_fetch` body into chat. Synthesize.
- Stay silent because it's not 100% sure. A snippet-grounded answer with a source link is the contract.

## Lifecycle

- One agent.run turn in main chat.
- Tool calls visible as chips: `web_search` → `web_fetch` (optional) → text reply.
- No DB writes (no task, no knowledge save unless user asked).

## Surprising / open questions

- **Snippet-only vs fetch-then-answer.** Latency vs accuracy. Brave snippets are usually enough for date/factoid queries; `web_fetch` is overhead. Heuristic: if the assistant trusts the snippet, skip the fetch. Watch for hallucinated dates from confident wrong snippets — citation discipline matters.
- **Source quality.** Brave returns wikipedia + news + government sites. No allowlist; the assistant picks. Worth observing: does the assistant pick wikipedia (good), random blog (bad), or government source (best)?
- **Citation format.** Plain URL? Inline link `[Bundestag.de](...)` markdown? Frontend renders markdown — markdown link reads cleaner. Codify in `behavior.md` if a pattern emerges.
- **No task chip.** Today the chip UX surfaces tool calls in chat. Confirm `web_search` + `web_fetch` chips render usefully (they may dump big snippet/body blobs).
