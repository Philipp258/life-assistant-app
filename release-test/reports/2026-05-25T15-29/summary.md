# Release test summary — 2026-05-25T15-29

**Run target:** Hetzner `157.180.120.244`, Ubuntu 26.04 LTS, branch `rev`, tested commit `f7f7f6c`.

**Verdict: green.** Fresh native install completed from the public one-command flow, Codex server-auth import configured the default `gpt-5.5` chat provider, and all seven release scenarios passed through the browser UI.

## Scoreboard

| # | Scenario | Status | Headline |
|---|----------|--------|----------|
| 01 | Install from README | green | Fresh install succeeded on Ubuntu 26.04 with standalone uv/Python 3.11, Node 22, Codex CLI, real sslip.io TLS, systemd service, and backup timer |
| 02 | First login and onboarding | green | Initial password login worked; Codex server auth imported from `/home/life-assistant/.codex/auth.json`; onboarding completed |
| 03 | Simple chat | green | Codex `gpt-5.5` answered a normal chat prompt |
| 04 | Schedule a reminder | green | Correct reminder task created for June 4, 2026 at 09:00 Berlin time |
| 05 | Background task | green | Espresso-machine research task ran autonomously and handed results back into main chat |
| 06 | Knowledge add and recall | green | Preference persisted to knowledge and was recalled after `/new` |
| 07 | Read a local file | green | Assistant read `/tmp/release-meeting-notes.txt` and summarized the file accurately |

## Validation Notes

- Final deployed commit: `f7f7f6c`.
- Runtime chat provider: `codex`.
- Runtime chat model: `gpt-5.5`.
- Codex plan metadata imported as `prolite`.
- `life-assistant.service` active/enabled.
- `life-assistant-backup.timer` active/enabled.
- Codex CLI installed at `/usr/bin/codex`; `codex login status` reports logged in.
- Final journal check found no tracebacks, model errors, or runner failures.

## Fixes Made During This Cycle

- Avoided a harmless first-install cert hook warning by only restarting `life-assistant.service` when the unit already exists/runs.
- Forced OAuth refresh during Codex server-auth import so stale but not-yet-expired access tokens are not stored in the DB.
- Disabled live token streaming for Codex runner turns because the streaming node path could stall while the normal node execution path completed. Final/tool messages still persist and render correctly.

## Known Non-Blocking Warnings

- Frontend build still emits the existing Tailwind CSS minify warning for an unusual selector and the existing Vite chunk-size warning.
- Public internet scanners hit a few malformed URLs during the run; these produced ordinary access log 404s, not application errors.
