# Release test

A scenario sweep run by an autonomous coding agent against a fresh,
throwaway VPS. The goal is to catch regressions in the user-facing
experience — setup, onboarding, chat, tasks, reminders, knowledge,
skills — before a release goes out.

The scenarios are intentionally vague. They describe what a user wants
to accomplish, not which buttons to press. That way they survive UI
and feature changes without constant editing.

## How a release test goes

You provision the server yourself, hand its address to the agent, walk
away for ~30 minutes, then destroy the server. The agent writes a
report folder into `reports/`.

### 1. Provision a VPS

Whatever Hetzner image and size you like, as long as it matches the
supported target in the project README. A small CX22 with Ubuntu 24.04
is enough.

You need:

- The server's public IP.
- Root SSH access from your laptop (key already loaded in your agent).

How you create it is up to you — Hetzner Console, `hcloud` CLI, or any
other provider that gives you a fresh Ubuntu box with ports 80 and 443
open. Pay by the hour, destroy when done.

### 2. Record the run target

Create `release-test/.current-run` with two lines:

```
IP=<public ip>
RUN_ID=<YYYY-MM-DDTHH-MM>
```

`RUN_ID` is just a folder name for the report. Pick anything that
sorts; an ISO-ish timestamp is fine.

### 3. Launch the agent

From this directory, open an autonomous Claude Code session and tell
it:

```
Run RUNNER.md.
```

The agent reads `RUNNER.md`, works through every file in `scenarios/`
in order, and writes notes + a summary into `reports/<RUN_ID>/`.

It will SSH into the server for setup-phase work and use a browser
(via the agent-browser skill) for app-phase work. It is not allowed to
modify this repo or open PRs.

### 4. Destroy the server

When the agent stops, destroy the VPS through whatever interface you
created it with. Confirm it is gone — the box is internet-exposed and
holds whatever the agent typed into it.

### 5. Review the report

`reports/<RUN_ID>/summary.md` is the top-level read. Per-scenario
detail lives in `reports/<RUN_ID>/scenarios/<id>/notes.md`.

To check for regressions, diff the new summary against the previous
run's summary.

## What lives here

- `RUNNER.md` — the agent's master prompt. Stable across releases.
- `scenarios/` — one file per user story. Stable; add new ones over
  time, edit existing ones only when the intent itself changes.
- `rubric.md` — how the agent rates each scenario.
- `reports/` — every run, kept in the repo.
- `.current-run` — gitignored handoff from you to the agent.

## Adding a scenario

Only add a scenario when a new user-visible capability becomes stable
enough that a regression in it would be a release blocker. Write the
file as intent + done-when + what to rate. Do not encode UI paths,
URLs, button names, or step lists — those rot. If you cannot describe
the scenario without naming a specific button, it is not stable enough
yet.