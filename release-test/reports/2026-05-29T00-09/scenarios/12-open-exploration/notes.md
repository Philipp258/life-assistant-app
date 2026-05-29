# 12 — Open exploration

**Status:** green

## Tried

- Reopened Settings after Codex import and after self-update.
- Opened Notifications.
- Checked root service invariants on the VPS after retest.
- Looked for regressions around the areas that failed in the previous report.

## Worked

- Codex Settings stayed coherent after import: configured state, `/root/.codex/auth.json`, “Available for refresh,” and “Refresh server login.”
- Notifications page loaded and clearly showed permission/subscription state.
- Services remained root-run after install, manual update, and chat self-update.
- Previous blockers were resolved: install URL, Knowledge `New`, self-update, and Codex configured-state wording.

## Noteworthy

- Notifications showed browser permission as denied in the test browser. I did not try to change browser notification permission.
- The Settings Tools section displays the saved Brave API key in the input after saving. That may be acceptable for a single-user local admin app, but it is visibly plaintext.
- Browser automation logs produced repeated Statsig rate-limit warnings from the Browser plugin; this did not appear to be app behavior.
- Public VPS logs showed random internet probes for unrelated paths. The app returned normal static/404 responses.

## Rating

Green. Open exploration found non-blocking notes only.
