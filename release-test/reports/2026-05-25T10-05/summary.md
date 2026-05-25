# Release test summary — 2026-05-25T10-05

**Run target:** Hetzner `178.105.219.48`, Ubuntu 26.04 LTS, branch `rev`, final tested commit `d121593`.

**Verdict: close to shippable, with two caveats.** The final native installer passes on Ubuntu 26.04 and all app scenarios complete with a valid Codex auth blob. Remaining concerns are a not-perfectly-clean install run because a blocker was fixed mid-test, and poor user-facing error detail for expired Codex auth.

## Scoreboard

| # | Scenario | Status | Headline |
|---|----------|--------|----------|
| 01 | Install from README | yellow | Final installer passed on Ubuntu 26.04, but only after a mid-run uv cwd fix and raw-cache workaround |
| 02 | First login and onboarding | yellow | Works with fresh Codex auth; expired auth still surfaces as vague connection error |
| 03 | Simple chat | green | Three-turn chat was coherent and context-aware |
| 04 | Schedule a reminder | green | Correct reminder task created for June 3, 2026 at 08:00 |
| 05 | Background task | green | Espresso-machine research task ran autonomously and handed back results |
| 06 | Knowledge add and recall | green | Preference persisted and recalled in a fresh chat |
| 07 | Read a local file | green | Assistant read `/tmp/release-meeting-notes.txt` and summarized accurately |

## Top Friction Points

1. **Installer uv cwd bug found and fixed during the run.** Commit `fd02647` failed at `uv python install` with `/root/uv.toml` permission denied. Follow-up commit `d121593` runs uv from `/home/life-assistant`; the final branch-url rerun passed.
2. **Expired Codex auth is still confusing to users.** The stale release-test `codex-auth.json` failed refresh with `401 Unauthorized`, but chat showed only `ModelAPIError: Connection error`. Logs had the useful `Codex CLI session expired... paste the new auth.json` message.
3. **The release-test browser could not paste/type long credentials.** This appears to be a browser automation limitation (`virtual clipboard is not installed`), not an app bug. Long provider auth was configured through the authenticated settings API.
4. **Fresh one-shot final-commit install still deserves one more clean VPS pass.** The final branch idempotent rerun passed, and the successful install exercised all late installer steps, but the machine was no longer fully clean after the first failed attempts.

## Regression Check

Compared with `2026-05-24T00-00`, the release is dramatically healthier:

- Ubuntu 26.04 install no longer fails on missing distro `python3.11`.
- Node 22 path works.
- sslip.io real cert issuance worked.
- Codex default `gpt-5.5` works with a valid ChatGPT/Codex auth blob.
- Provider save ambiguity is no longer blocking configuration.
- App scenarios 03-07 are no longer blocked by provider setup.

Remaining release blocker candidate: expired Codex auth should surface a specific actionable message in chat/settings instead of generic connection failure.
