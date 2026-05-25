# 013 — Read a local file, save action items to knowledge

## Scenario

User says in main chat:

> I dumped today's meeting notes to /tmp/meeting.md. Save the action items as a knowledge note.

(Or an absolute path on the user's machine. the assistant runs on the same host — it can actually open the file.)

## Expected user-visible behavior

- the assistant calls `read_file("/tmp/meeting.md")`. Absolute path supported by `read_file` (`backend/app/agent/tools/fs.py`).
- the assistant extracts action items from the body.
- the assistant calls `save_knowledge("meetings/<date>-action-items.md", body, title="Meeting action items YYYY-MM-DD")` — curated path (frontmatter + chip + tree update), not raw `write_file`.
- the assistant replies: "Saved 4 action items under `meetings/2026-04-30-action-items.md`."
- Knowledge tree in next system prompt build includes the new entry.

## What the assistant should NOT do

- Use `bash cat /tmp/meeting.md` instead of `read_file`. `bash` is for things `read_file` can't do; for reading a text file, `read_file` returns line-numbered text and is cheaper.
- Use `write_file` to put the note under `data/knowledge/`. `RAW_TOOLS_PROMPT` tells the agent to prefer `save_knowledge` for memory updates — bypasses frontmatter + chip otherwise.
- Save the entire raw meeting body. The user asked for action items; synthesize.

## Expected interaction

```
user: I dumped today's meeting notes to /tmp/meeting.md. Save the action items as a knowledge note.
assistant: [tool] read_file("/tmp/meeting.md")
assistant: [tool] save_knowledge("meetings/2026-04-30-action-items.md", "...action items...", title="...")
assistant: Saved 4 action items under `meetings/2026-04-30-action-items.md`.
```

## Lifecycle

- One agent.run turn in main chat (or possibly two if model splits read + summarize + save).
- No task created. Direct chat operation.
- Knowledge tree updated atomically by `save_knowledge`; visible in next message's system prompt + Knowledge screen tree.

## Surprising / open questions

- **Path scope.** `read_file` accepts absolute paths — `/tmp/`, `~/Downloads/`, anywhere the backend process can read. Reasonable for personal-machine single-user. If the assistant ever runs as a service for someone else, revisit.
- **Binary refusal.** If user points at a PDF or image, `read_file` rejects with "binary file". the assistant should fall back gracefully — message "that's a binary file; I can't read PDFs yet" instead of looping.
- **Choosing a knowledge path.** the assistant picks `meetings/<date>-action-items.md`. Folder convention not yet established — first meeting note creates the folder. Roadmap: should `behavior.md` codify folder conventions? (Probably yes once the user actually uses the assistant for real meetings.)
- **Date in filename.** the assistant needs `now()` to get the date. Already wired (`backend/app/agent/__init__.py` `now` tool).
