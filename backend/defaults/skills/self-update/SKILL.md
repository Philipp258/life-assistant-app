---
name: self-update
description: Deploy the latest Life Assistant code to the VPS - pulls main, rebuilds, restarts. Use when the user says "deploy", "ship it", "update yourself", or "pull latest".
---

# Self-update

Life Assistant can redeploy itself by triggering the `life-assistant-update.service`
systemd unit on the VPS. The `self_update` tool is the interface; use this
skill when the user wants the live app to pick up already-merged code.

## When to use

- User says: "deploy", "ship it", "pull latest", "update yourself",
  "redeploy", "restart with new code".
- After the user merges a PR they want live.

## When NOT to use

- Local dev (`make dev`). The tool refuses outside systemd anyway, but
  don't pretend you're going to deploy when you can't.
- Mid-task on something fragile. A restart drops the listen socket for
  ~2s; SSE clients reconnect, but if you're in the middle of a critical
  multi-step run, finish first.

## How

Call `self_update()`. It returns immediately with
`{ok: true, message: ...}` once systemctl has accepted the start. The
actual work (git pull, uv sync, alembic migrate, pnpm build, restart)
takes 30-60s and runs in a separate oneshot service. Life Assistant's process
gets killed during the restart and comes back on the new code.

In-flight autonomous tasks survive — `app.main` lifespan re-wakes them
on the next boot.

## What if it fails

- `{ok: false, reason: "not running under systemd..."}` — you're in dev.
  Tell the user, suggest manual `git pull && make dev`.
- `{ok: false, reason: "systemctl exited N"}` — sudoers entry missing
  or the unit file isn't installed. Surface the stderr to the user.

## After deploying

If you are still running after the restart, verify with `/api/health` (no auth
required) or ask the user to refresh. If something looks broken, propose a
rollback before running one.
