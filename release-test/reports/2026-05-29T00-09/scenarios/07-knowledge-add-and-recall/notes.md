# 07 — Knowledge add and recall

**Status:** green

## Tried

- Asked Ada to remember a meeting-summary preference.
- Opened the generated knowledge note.
- Created a manual folder and manual note from the Knowledge UI.
- Edited the note body in the UI.
- Started a fresh chat with `/new` and asked Ada to recall both the meeting preference and manual note.

## Worked

- Assistant-created knowledge landed at `preferences/meeting-summaries.md` as readable markdown.
- The new Knowledge sheet supported folder creation, path preview, note creation, and navigation to the created note.
- Manual edit persisted.
- Fresh chat used `read_knowledge` and recalled both the meeting-summary preference and the manual note content.

## Friction

- `/new` works for a fresh chat, but it is not discoverable from the visible UI. Pressing Enter ran it; clicking the normal send button did not trigger the slash command in the test browser.
- During folder creation, the sheet briefly left an odd stale-looking creation state after submit, but canceling it and continuing worked. This did not prevent creating the folder or note.

## Rating

Green. The persistence and recall goals worked; fresh-chat discoverability remains worth improving later.
