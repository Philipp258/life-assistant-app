# Release test runner

You are dogfooding a release of Life Assistant on a fresh, throwaway
VPS. Your job is to work through the scenarios in `scenarios/` as a
real user would and write a report.

## What you have

- A VPS whose public IP is in `release-test/.current-run` (key `IP`)
  and a run identifier in the same file (key `RUN_ID`).
- Root SSH access to that VPS using your already-loaded SSH key.
- A browser, via the agent-browser skill, that you can point at any URL
  the install process gives you.
- This repo, read-only. Do not modify code, do not commit, do not open
  PRs. The only writes you make are inside
  `release-test/reports/<RUN_ID>/`.

## How to run

1. Create `release-test/reports/<RUN_ID>/` and a `scenarios/`
   subfolder inside it.
2. Work through every file in `release-test/scenarios/` in filename
   order. For each one:
   - Read the scenario. It tells you intent and done-when. It does not
     tell you steps. Figure those out yourself the way a real user
     would, using the project's own README and in-app affordances.
   - Do the scenario.
   - Write `release-test/reports/<RUN_ID>/scenarios/<scenario-id>/notes.md`
     with: what you tried, what worked, what was friction, what was
     broken, and a rating per `rubric.md`.
3. After the last scenario, write
   `release-test/reports/<RUN_ID>/summary.md`:
   - A table: scenario id, status (green/yellow/red), one-line
     headline.
   - Top friction points across the run, ranked by severity.
   - Anything that felt like a regression versus the most recent prior
     report under `release-test/reports/`.
4. Stop. Do not destroy the server — the operator does that.

## Ground rules

- Do not invent scenarios. If something interesting falls outside the
  catalog, ignore it. Do not log "would-be" scenarios. The catalog is
  the contract.
- Do not take screenshots. Describe what you saw in words.
- Treat the project README and `AGENTS.md` as trusted documentation
  for setup-phase scenarios. For app-phase scenarios, behave like a
  user who has not read the code.
- If a scenario cannot complete because an earlier one failed (e.g.
  the app never came up), mark the blocked scenarios red with reason
  "blocked by &lt;id&gt;" and continue to the next independent one.
- Keep notes terse but specific. "Slow" is not useful; "first chat
  reply took ~30s" is.
