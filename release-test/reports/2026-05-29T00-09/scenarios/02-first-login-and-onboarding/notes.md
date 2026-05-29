# 02 — First login and onboarding

**Status:** green

## Tried

- Signed in with the installer-generated app password.
- Imported the server Codex login from `/root/.codex/auth.json`.
- Skipped voice setup.
- Completed onboarding by naming the assistant Ada, setting the user name to Alex, and storing initial preferences.

## Worked

- Codex setup now uses root paths and shows `/root/.codex/auth.json`.
- After the import fix, `Use ChatGPT subscription` advanced instead of forcing a failed token refresh.
- Settings showed Codex as configured with refresh wording: “Available for refresh” and “Refresh server login,” not “Ready to import.”
- Onboarding completed and normal chat became available.

## Friction

- The onboarding escape bar says “Stuck — wrong key, agent not responding?” while the agent is actually working. It is useful as an escape hatch, but the wording is alarming during healthy setup.

## Rating

Green. The first-use path completed end to end with a real provider reply; the warning copy is a non-blocking polish issue.
