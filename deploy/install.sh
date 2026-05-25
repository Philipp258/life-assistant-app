#!/usr/bin/env bash
# One-shot installer for Life Assistant on a fresh Ubuntu 24.04 VPS.
# Run as root. Idempotent — safe to re-run after editing files.
#
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/deploy/install.sh | sudo bash
#
# After this finishes:
#   1. systemctl restart life-assistant
#   2. browse to http://<vps-ip>/    (login password printed below)
#   3. finish provider setup in the UI

set -euo pipefail

REPO_URL=${LIFE_ASSISTANT_REPO_URL:-https://github.com/Philipp258/life-assistant.git}
REPO_DIR=/opt/life-assistant
DATA_DIR=/var/lib/life-assistant/data
BACKUP_DIR=/var/lib/life-assistant/backups
ETC_DIR=/etc/life-assistant

if [ "$(id -u)" -ne 0 ]; then
  echo "install.sh must run as root" >&2
  exit 1
fi

echo "==> system packages"
apt-get update -qq
apt-get install -y -qq \
  python3.11 python3.11-venv python3-pip \
  git curl ca-certificates sqlite3 \
  build-essential

echo "==> nodejs 20 (nodesource)"
if ! command -v node >/dev/null || ! node -v | grep -q '^v20'; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi
corepack enable
corepack prepare pnpm@10.33.2 --activate

echo "==> legacy service user"
if ! id life-assistant >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /home/life-assistant --shell /usr/sbin/nologin life-assistant
fi

echo "==> directories"
install -d -o life-assistant -g life-assistant -m 755 "$REPO_DIR"
install -d -o life-assistant -g life-assistant -m 750 "$DATA_DIR" "$BACKUP_DIR"
install -d -o root -g root  -m 755 "$ETC_DIR"

echo "==> clone repo"
if [ ! -d "$REPO_DIR/.git" ]; then
  sudo -u life-assistant git clone --quiet "$REPO_URL" "$REPO_DIR"
else
  sudo -u life-assistant git -C "$REPO_DIR" fetch --quiet origin main
  sudo -u life-assistant git -C "$REPO_DIR" reset --hard origin/main
fi

echo "==> data symlink"
# Life Assistant reads/writes data/ via paths relative to the repo. Symlink it
# to the persistent volume so updates can never wipe user data.
if [ -e "$REPO_DIR/data" ] && [ ! -L "$REPO_DIR/data" ]; then
  # First boot: move whatever the repo shipped into the persistent dir.
  mv "$REPO_DIR/data"/* "$DATA_DIR/" 2>/dev/null || true
  rm -rf "$REPO_DIR/data"
fi
sudo -u life-assistant ln -snf "$DATA_DIR" "$REPO_DIR/data"

echo "==> python venv + uv"
if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
  sudo -u life-assistant python3.11 -m venv "$REPO_DIR/.venv"
fi
sudo -u life-assistant "$REPO_DIR/.venv/bin/pip" install -q --upgrade pip uv

echo "==> env file"
SEED_LOGIN_PASS=""
if [ ! -f "$ETC_DIR/life-assistant.env" ]; then
  SESSION_SECRET_VAL=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  SEED_LOGIN_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
  cat > "$ETC_DIR/life-assistant.env" <<EOF
ENV=prod
SERVE_FRONTEND=true
DATABASE_URL=sqlite:///$DATA_DIR/life_assistant.db

# Signs the session cookie. Rotating this invalidates all logins.
SESSION_SECRET=$SESSION_SECRET_VAL

# Optional — Langfuse tracing (all three required to enable)
# LANGFUSE_PUBLIC_KEY=
# LANGFUSE_SECRET_KEY=
# LANGFUSE_BASE_URL=https://cloud.langfuse.com
# Provider credentials and Brave Search API key live in the DB — set them
# from Agent → Settings.
EOF
  chmod 640 "$ETC_DIR/life-assistant.env"
  chown root:life-assistant "$ETC_DIR/life-assistant.env"
fi

echo "==> first build"
sudo -u life-assistant "$REPO_DIR/deploy/update.sh" || true   # ok if already up to date
# update.sh exits 0 with no rebuild when already up to date; force a build
# on first install regardless so frontend/dist exists.
if [ ! -d "$REPO_DIR/frontend/dist" ]; then
  sudo -u life-assistant bash -c "cd $REPO_DIR/backend && $REPO_DIR/.venv/bin/uv sync --frozen"
  sudo -u life-assistant bash -c "cd $REPO_DIR/backend && $REPO_DIR/backend/.venv/bin/alembic upgrade head"
  sudo -u life-assistant bash -c "cd $REPO_DIR/frontend && pnpm install --frozen-lockfile && pnpm build"
fi

if [ -n "$SEED_LOGIN_PASS" ]; then
  echo "==> seed initial login password"
  # Migrations have run via update.sh / first-build branch above, so the
  # users table exists. The CLI creates the singleton row if missing.
  sudo -u life-assistant bash -c "set -a; source $ETC_DIR/life-assistant.env; set +a; cd $REPO_DIR/backend && $REPO_DIR/backend/.venv/bin/python -m app.users.set_password '$SEED_LOGIN_PASS'"
  echo
  echo "==============================================================="
  echo "  Life Assistant login password: $SEED_LOGIN_PASS"
  echo "  (rotate later with:  make set-password PASSWORD=<new>)"
  echo "==============================================================="
  echo
fi

echo "==> systemd units"
install -o root -g root -m 644 "$REPO_DIR/deploy/life-assistant.service"        /etc/systemd/system/life-assistant.service
install -o root -g root -m 644 "$REPO_DIR/deploy/life-assistant-update.service" /etc/systemd/system/life-assistant-update.service
install -o root -g root -m 644 "$REPO_DIR/deploy/life-assistant-backup.service" /etc/systemd/system/life-assistant-backup.service
install -o root -g root -m 644 "$REPO_DIR/deploy/life-assistant-backup.timer"   /etc/systemd/system/life-assistant-backup.timer
chmod +x "$REPO_DIR/deploy/update.sh" "$REPO_DIR/deploy/backup.sh"

echo "==> sudoers"
install -o root -g root -m 440 "$REPO_DIR/deploy/sudoers.life-assistant" /etc/sudoers.d/life-assistant
visudo -c -q -f /etc/sudoers.d/life-assistant

echo "==> firewall"
if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
  ufw allow 8000/tcp >/dev/null
fi

echo "==> enable + start"
systemctl daemon-reload
systemctl enable --now life-assistant.service life-assistant-backup.timer

echo
echo "done. logs: journalctl -u life-assistant -f"
