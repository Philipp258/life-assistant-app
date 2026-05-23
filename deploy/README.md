# Deploying Life Assistant

Single-VPS, single-process deploy. uvicorn binds `0.0.0.0:8000`, serves
the built SPA and the `/api/*` routes from one process. SQLite + `data/`
lives under `/var/lib/life-assistant/`. systemd supervises. Life Assistant can self-update
via a chat tool that triggers `life-assistant-update.service`.

## Why no DNS / TLS yet

The current setup runs on a public IP without a domain or TLS. Traffic is
plain HTTP. To stop random scans from using your configured provider credentials,
the backend has an HTTP basic-auth middleware in front of every route except
`/api/health`. Credentials live in `/etc/life-assistant/life-assistant.env`.
This is a stop-gap — once you wire DNS, drop Caddy in front and replace
basic auth with a real session cookie.

## Prerequisites

- Ubuntu 24.04 VPS, root SSH access, public IP
- Port 8000 open
- At least one supported chat provider credential for in-app setup

## Install

```bash
ssh root@<vps-ip>
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/deploy/install.sh \
  | LIFE_ASSISTANT_REPO_URL=https://github.com/<owner>/<repo>.git bash
```

The installer prints the generated login password at the end. Save it.

Then:

```bash
systemctl restart life-assistant
```

Browse to `http://<vps-ip>:8000/`, sign in with the printed password, finish
provider setup in the UI, then send a chat. Done.

## HTTPS without a domain

Push notifications and microphone access require HTTPS. If you do not own a
domain, see [`/docs/https-no-domain.md`](../frontend/public/docs/https-no-domain.md)
for a thin Tailscale Serve setup that gives Life Assistant a stable `https://*.ts.net` URL.
Once Life Assistant is reachable over HTTPS, the in-app setup flow can take over.

## Self-update from chat

Tell the assistant in chat: "deploy latest" (or anything that triggers the
`self-update` skill). The agent reads the skill and runs
`sudo systemctl start life-assistant-update.service` via `bash` in a task chat.
The oneshot service runs `deploy/update.sh`: git pull, uv sync, alembic
upgrade, frontend build, then `systemctl restart life-assistant`. Restart
drops the listen socket for ~2s; the autonomous-task watchdog re-wakes any
in-flight tasks on the new process.

## Manual update

```bash
sudo -u life-assistant /opt/life-assistant/deploy/update.sh
```

## Migration squash — one-time stamp

Do this once, before the first update that pulls the squash commit.

The 43-migration chain was collapsed into a single `0001_baseline`.
The live DB's `alembic_version` still points at the old head
`7d8e9f0a1b2c`, whose file no longer exists, so a plain
`alembic upgrade head` aborts ("Can't locate revision …") before any
migration runs. Stamp the DB onto the baseline first — the box is
already structurally at the old head, so this only rewrites the
version marker, it does not touch the schema or data:

```bash
# 1. Snapshot first (safety net — restore per "Backups > Restore" if needed).
sudo systemctl start life-assistant-backup.service

# 2. Point the version marker at the baseline (--purge clears the stale row).
sudo -u life-assistant bash -c \
  'cd /opt/life-assistant/backend && /opt/life-assistant/.venv/bin/alembic stamp 0001_baseline --purge'

# 3. Verify, then update normally.
sudo -u life-assistant bash -c \
  'cd /opt/life-assistant/backend && /opt/life-assistant/.venv/bin/alembic current'   # -> 0001_baseline
sudo -u life-assistant /opt/life-assistant/deploy/update.sh
```

After the stamp, every subsequent `alembic upgrade head` is a no-op on
this box (the baseline self-guards: it skips creates when `tasks`
already exists). Fresh installs get the full schema from the baseline
normally. Default routines (weekly reflection, daily consolidation,
improve-life-assistant collect/process, weekly disk-space) are no longer seed
migrations — `app.tasks.default_routines.ensure_default_routines`
seeds them idempotently at boot, so the existing rows on this box are
left as-is.

## Logs

```bash
journalctl -u life-assistant -f             # main service
journalctl -u life-assistant-update -n 200  # last update
journalctl -u life-assistant-backup -n 50   # last backup
```

## Backups

The legacy `life-assistant-backup.timer` fires daily and runs `deploy/backup.sh`, which
takes a transactionally-consistent SQLite snapshot of `life_assistant.db` and
tars it together with `data/core/`, `data/knowledge/`, and
`data/skills/` (user-installed skills only — defaults live in the repo
under `backend/defaults/skills/` and don't need backup) into
`/var/lib/life-assistant/backups/life-assistant-YYYY-MM-DD-HHMMSS.tar.gz`. Last 7 retained.

### Restore

```bash
# Pick a snapshot.
ls -1t /var/lib/life-assistant/backups/life-assistant-*.tar.gz

# Stop the service to avoid clobbering live writes.
sudo systemctl stop life-assistant

# Untar over the data dir. The tarball restores life_assistant.db to a clean
# state; WAL sidecars are intentionally absent and SQLite recreates
# them on first connect.
sudo -u life-assistant tar -xzf /var/lib/life-assistant/backups/life-assistant-<stamp>.tar.gz \
  -C /var/lib/life-assistant/data

# Drop any stale WAL sidecars from the previous run.
sudo -u life-assistant rm -f /var/lib/life-assistant/data/life_assistant.db-shm /var/lib/life-assistant/data/life_assistant.db-wal

sudo systemctl start life-assistant
```

Legacy deployments whose `/etc/life-assistant/life-assistant.env` still points `DATABASE_URL` at
`life-assistant.db` restore the same way, but the archive contains `life-assistant.db`; remove
`life-assistant.db-shm` and `life-assistant.db-wal` instead.

## Rollback

```bash
sudo -u life-assistant bash -c '
  cd /opt/life-assistant
  git log --oneline -20
  git reset --hard <good-sha>
  cd backend && /opt/life-assistant/.venv/bin/uv sync --frozen && /opt/life-assistant/.venv/bin/alembic upgrade head
  cd ../frontend && pnpm install --frozen-lockfile && pnpm build
'
sudo systemctl restart life-assistant
```

If a migration broke things, restore from the latest tarball (see
**Backups → Restore** above).

## File layout

| Path                              | Owner       | Purpose                              |
|-----------------------------------|-------------|--------------------------------------|
| `/opt/life-assistant`                       | life-assistant:life-assistant   | Repo checkout                        |
| `/opt/life-assistant/.venv`                 | life-assistant:life-assistant   | Python venv                          |
| `/opt/life-assistant/data` → `/var/lib/life-assistant/data` | symlink | Repo's `data/` points at persistent volume |
| `/var/lib/life-assistant/data/life_assistant.db`      | life-assistant:life-assistant   | SQLite (+ WAL sidecars)              |
| `/var/lib/life-assistant/backups/`          | life-assistant:life-assistant   | Daily snapshots, last 7              |
| `/etc/life-assistant/life-assistant.env`              | root:life-assistant 640 | Secrets                            |
| `/etc/systemd/system/life-assistant*.{service,timer}` | root | systemd units                  |
| `/etc/sudoers.d/life-assistant`             | root:root 440 | Limited sudo for restart + update  |

## Follow-ups (not in this deploy)

- DNS + TLS via Caddy (replace basic-auth with session cookies)
- GitHub Actions push-to-deploy (currently agent-triggered or manual)
- Off-box backup destination (S3/B2)
