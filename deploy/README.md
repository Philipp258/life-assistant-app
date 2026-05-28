# Deploying Life Assistant

Single-VPS, single-process deploy. uvicorn binds `0.0.0.0:443` directly, with
its own TLS termination — no reverse proxy. It serves the built SPA and the
`/api/*` routes from one process. SQLite + `data/` lives under
`/var/lib/life-assistant/`. systemd supervises. Life Assistant can self-update
via a chat tool that triggers `life-assistant-update.service`.

## TLS by default

`install.sh` derives a stable hostname from the VPS public IP via
[sslip.io](https://sslip.io) — e.g. `1-2-3-4.sslip.io` resolves straight back
to `1.2.3.4`. It then runs certbot in `--standalone` mode to obtain a real
Let's Encrypt certificate for that name, drops the cert into
`/etc/life-assistant/tls/`, and starts uvicorn with `--ssl-keyfile` /
`--ssl-certfile` flags. No domain purchase, no reverse proxy, no manual DNS
step. The cert renews automatically via `certbot.timer`; the renewal hook at
`/etc/letsencrypt/renewal-hooks/deploy/life-assistant.sh` re-copies the new
cert and restarts the service.

What sslip.io sees: DNS lookups for the encoded hostname. They do not see
HTTPS traffic, which goes directly between the browser and your VPS.

If you would rather use your own domain, see
[Custom domain](#custom-domain) below. If you would rather not have any public
HTTPS endpoint at all, see [Tailnet-only deployment](#tailnet-only-deployment).

## Prerequisites

- Ubuntu/Debian-style systemd VPS with `apt`, root SSH access, public IPv4
- Ports 80 (for ACME) and 443 (for the app) open
- At least one supported chat provider credential for in-app setup

## Install

```bash
ssh root@<vps-ip>
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/deploy/install.sh \
  | LIFE_ASSISTANT_REPO_URL=https://github.com/<owner>/<repo>.git bash
```

The installer prints the HTTPS URL and the generated login password at the
end. Save them.

Optional install-time overrides:

- `LIFE_ASSISTANT_DOMAIN=la.example.com` uses your own DNS name instead of the
  derived sslip.io hostname. Point the `A` record at the VPS before running the
  installer.
- `LIFE_ASSISTANT_CERTBOT_STAGING=1` uses Let's Encrypt staging. Use this only
  for release-test dry runs; browsers will not trust the certificate.

Open the printed URL, sign in with the printed password, finish provider
setup in the UI, then send a chat. Done.

## Custom domain

If you own a domain (e.g. `la.example.com`) and would rather not use the
sslip.io URL:

1. Point an `A` record at the VPS public IP and wait for it to propagate.
2. On the VPS:

   ```bash
   sudo systemctl stop life-assistant
   sudo certbot certonly --standalone -d la.example.com \
     --agree-tos -m you@example.com -n
   sudo /etc/letsencrypt/renewal-hooks/deploy/life-assistant.sh
   sudo systemctl start life-assistant
   ```

3. (Optional) Revoke / delete the old sslip.io cert with
   `sudo certbot delete --cert-name <old-hostname>` to keep the renewal list
   clean. Only do this after the new cert is loaded successfully.

The deploy hook always copies the most recent lineage from
`/etc/letsencrypt/live/`, so as long as there is exactly one active cert,
uvicorn picks it up on the next restart.

## Tailnet-only deployment

For maximum privacy (no public TLS endpoint, no third-party DNS), deploy on
the tailnet instead. Skip the certbot step by uninstalling certbot or by
having the firewall closed during install (the script will fail loud at the
cert step; bind uvicorn to `127.0.0.1:8000` afterwards), then expose it via
Tailscale Serve — see [`/docs/https-no-domain.md`](../frontend/public/docs/https-no-domain.md).

## Self-update from chat

Tell the assistant in chat: "deploy latest" (or anything that triggers the
`self-update` skill). The agent reads the skill and runs
`systemctl start life-assistant-update.service` via `bash` in a task chat.
The oneshot service runs `deploy/update.sh`: git pull, uv sync, alembic
upgrade, frontend build, then `systemctl restart life-assistant`. Restart
drops the listen socket for ~2s; the autonomous-task watchdog re-wakes any
in-flight tasks on the new process.

## Manual update

```bash
/opt/life-assistant/deploy/update.sh
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
cd /opt/life-assistant/backend
/opt/life-assistant/backend/.venv/bin/alembic stamp 0001_baseline --purge

# 3. Verify, then update normally.
/opt/life-assistant/backend/.venv/bin/alembic current   # -> 0001_baseline
/opt/life-assistant/deploy/update.sh
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
tar -xzf /var/lib/life-assistant/backups/life-assistant-<stamp>.tar.gz \
  -C /var/lib/life-assistant/data

# Drop any stale WAL sidecars from the previous run.
rm -f /var/lib/life-assistant/data/life_assistant.db-shm /var/lib/life-assistant/data/life_assistant.db-wal

sudo systemctl start life-assistant
```

Legacy deployments whose `/etc/life-assistant/life-assistant.env` still points `DATABASE_URL` at
`life-assistant.db` restore the same way, but the archive contains `life-assistant.db`; remove
`life-assistant.db-shm` and `life-assistant.db-wal` instead.

## Rollback

```bash
cd /opt/life-assistant
git log --oneline -20
git reset --hard <good-sha>
cd backend && /root/.local/bin/uv python install 3.11 --managed-python && /root/.local/bin/uv sync --frozen --python 3.11 --managed-python && /opt/life-assistant/backend/.venv/bin/alembic upgrade head
cd ../frontend && pnpm install --frozen-lockfile && pnpm build
sudo systemctl restart life-assistant
```

If a migration broke things, restore from the latest tarball (see
**Backups → Restore** above).

## File layout

| Path                              | Owner       | Purpose                              |
|-----------------------------------|-------------|--------------------------------------|
| `/opt/life-assistant`                       | root:root   | Repo checkout                        |
| `/root/.local/bin/uv`                       | root:root   | Standalone uv binary                 |
| `/opt/life-assistant/backend/.venv`         | root:root   | Backend Python venv                  |
| `/opt/life-assistant/data` → `/var/lib/life-assistant/data` | symlink | Repo's `data/` points at persistent volume |
| `/var/lib/life-assistant/data/life_assistant.db`      | root:root   | SQLite (+ WAL sidecars)              |
| `/var/lib/life-assistant/backups/`          | root:root   | Daily snapshots, last 7              |
| `/etc/life-assistant/life-assistant.env`              | root:root 640 | Secrets                            |
| `/etc/life-assistant/tls/{cert,key}.pem`              | root:root | TLS cert + key (copied from Let's Encrypt on renewal) |
| `/etc/letsencrypt/`                                   | root | Let's Encrypt state + cert lineage             |
| `/etc/letsencrypt/renewal-hooks/deploy/life-assistant.sh` | root:root 755 | Post-renewal: re-copy cert, restart service |
| `/etc/systemd/system/life-assistant*.{service,timer}` | root | systemd units                  |

## Follow-ups (not in this deploy)

- GitHub Actions push-to-deploy (currently agent-triggered or manual)
- Off-box backup destination (S3/B2)
