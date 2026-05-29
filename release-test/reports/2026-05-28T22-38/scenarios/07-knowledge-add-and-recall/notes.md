# 07 — Knowledge add and recall

Status: red
Severity: blocker

What I tried: asked the assistant to save a release-test codename, inspected the Knowledge UI, tried manual Knowledge `New`, edited the saved note, then started a fresh chat with `/new` and asked for the codename.

What worked: the assistant saved `Release test preferences` at `projects/release-test.md`. The Knowledge UI showed readable markdown. Editing the note worked; I changed the codename from `Copper Finch` to `Steel Finch`, and the saved markdown rendered correctly. `/new` created a fresh chat, and the assistant used `read_knowledge` to answer `Steel Finch`.

What broke: manual Knowledge `New` failed. Clicking `New` calls `window.prompt()`, and the browser logged `Error: prompt() is not supported.` No manual note was created and there was no in-app fallback or error message.

Rating: assistant-saved knowledge, editing, and recall work. Manual knowledge creation is blocked by the prompt-based UI.
