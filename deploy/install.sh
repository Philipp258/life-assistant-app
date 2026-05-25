#!/usr/bin/env bash
# One-shot installer for Life Assistant on a fresh Ubuntu/Debian systemd VPS.
# Run as root. Idempotent — safe to re-run after editing files.
#
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/deploy/install.sh | sudo bash
#
# After this finishes:
#   1. systemctl restart life-assistant
#   2. browse to https://<auto-derived-name>.sslip.io/  (URL + login password
#      printed at the end)
#   3. finish provider setup in the UI

set -euo pipefail

REPO_URL=${LIFE_ASSISTANT_REPO_URL:-https://github.com/Philipp258/life-assistant.git}
REF=${LIFE_ASSISTANT_REF:-main}
REPO_DIR=/opt/life-assistant
DATA_DIR=/var/lib/life-assistant/data
BACKUP_DIR=/var/lib/life-assistant/backups
ETC_DIR=/etc/life-assistant
UV_BIN=/home/life-assistant/.local/bin/uv
PENDING_PASSWORD_FILE=$ETC_DIR/initial-login-password

if [ "$(id -u)" -ne 0 ]; then
  echo "install.sh must run as root" >&2
  exit 1
fi

random_hex() {
  local bytes=$1
  od -An -N"$bytes" -tx1 /dev/urandom | tr -d ' \n'
}

ensure_pending_login_password() {
  SEED_LOGIN_PASS=""
  if [ -f "$PENDING_PASSWORD_FILE" ]; then
    IFS= read -r SEED_LOGIN_PASS < "$PENDING_PASSWORD_FILE" || true
  fi
  if [ -z "$SEED_LOGIN_PASS" ]; then
    SEED_LOGIN_PASS=$(random_hex 18)
    install -o root -g life-assistant -m 640 /dev/null "$PENDING_PASSWORD_FILE"
    printf '%s\n' "$SEED_LOGIN_PASS" > "$PENDING_PASSWORD_FILE"
  fi
}

echo "==> OS preflight"
if ! command -v apt-get >/dev/null 2>&1; then
  echo "unsupported OS: apt-get is required; expected an Ubuntu/Debian-style VPS" >&2
  exit 1
fi
if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
  echo "unsupported init system: systemd is required for Life Assistant services" >&2
  exit 1
fi
if [ ! -r /etc/os-release ]; then
  echo "unsupported OS: /etc/os-release is missing; expected Ubuntu/Debian-style Linux" >&2
  exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
echo "    OS: ${PRETTY_NAME:-unknown}"

echo "==> system packages"
apt-get update -qq
apt-get install -y -qq \
  sudo git curl ca-certificates sqlite3 \
  build-essential certbot

echo "==> nodejs 22+ (nodesource)"
NODE_MAJOR=0
if command -v node >/dev/null 2>&1; then
  NODE_MAJOR=$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || echo 0)
fi
if [ "$NODE_MAJOR" -lt 22 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
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

echo "==> clone repo (ref: $REF)"
if [ ! -d "$REPO_DIR/.git" ]; then
  sudo -u life-assistant git clone --quiet --branch "$REF" "$REPO_URL" "$REPO_DIR"
else
  sudo -u life-assistant git -C "$REPO_DIR" fetch --quiet origin "$REF"
  sudo -u life-assistant git -C "$REPO_DIR" reset --hard "origin/$REF"
fi

# Persist the deploy ref so update.sh stays on the same branch.
cat > "$ETC_DIR/deploy.env" <<EOF
REF=$REF
EOF
chmod 644 "$ETC_DIR/deploy.env"

echo "==> data symlink"
# Life Assistant reads/writes data/ via paths relative to the repo. Symlink it
# to the persistent volume so updates can never wipe user data.
if [ -e "$REPO_DIR/data" ] && [ ! -L "$REPO_DIR/data" ]; then
  # First boot: move whatever the repo shipped into the persistent dir.
  mv "$REPO_DIR/data"/* "$DATA_DIR/" 2>/dev/null || true
  rm -rf "$REPO_DIR/data"
fi
sudo -u life-assistant ln -snf "$DATA_DIR" "$REPO_DIR/data"

echo "==> uv + Python 3.11"
install -d -o life-assistant -g life-assistant -m 755 /home/life-assistant/.local /home/life-assistant/.local/bin
if [ ! -x "$UV_BIN" ]; then
  sudo -u life-assistant env HOME=/home/life-assistant UV_NO_MODIFY_PATH=1 \
    sh -c 'cd /home/life-assistant && curl -LsSf https://astral.sh/uv/install.sh | sh'
fi
sudo -u life-assistant env HOME=/home/life-assistant \
  sh -c "cd /home/life-assistant && '$UV_BIN' python install 3.11 --managed-python"

echo "==> env file"
SEED_LOGIN_PASS=""
if [ ! -f "$ETC_DIR/life-assistant.env" ]; then
  SESSION_SECRET_VAL=$(random_hex 32)
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
  ensure_pending_login_password
fi

echo "==> public IP + sslip.io hostname"
PUBLIC_IP=$(curl -fsS --max-time 10 https://api.ipify.org)
if [ -z "$PUBLIC_IP" ]; then
  echo "could not determine public IPv4 via api.ipify.org" >&2
  exit 1
fi
APP_HOSTNAME=${LIFE_ASSISTANT_DOMAIN:-}
if [ -z "$APP_HOSTNAME" ]; then
  APP_HOSTNAME="${PUBLIC_IP//./-}.sslip.io"
fi
echo "    public IP: $PUBLIC_IP"
echo "    hostname:  $APP_HOSTNAME"

echo "==> firewall (open 80 for ACME, 443 for app)"
if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
  ufw allow 80/tcp  >/dev/null
  ufw allow 443/tcp >/dev/null
  # Old plaintext port — close if it was opened by a previous install.
  ufw delete allow 8000/tcp >/dev/null 2>&1 || true
fi

echo "==> Let's Encrypt cert via certbot --standalone"
install -d -o root -g root -m 755 /etc/letsencrypt/renewal-hooks/deploy
install -o root -g root -m 755 "$REPO_DIR/deploy/certbot-deploy.sh" \
  /etc/letsencrypt/renewal-hooks/deploy/life-assistant.sh
# Idempotent: if cert exists and isn't near expiry, certbot keeps it.
CERTBOT_EXTRA_ARGS=()
if [ "${LIFE_ASSISTANT_CERTBOT_STAGING:-}" = "1" ]; then
  CERTBOT_EXTRA_ARGS+=(--staging)
fi
if ! certbot certonly \
  "${CERTBOT_EXTRA_ARGS[@]}" \
  --standalone \
  --non-interactive \
  --agree-tos \
  --register-unsafely-without-email \
  --keep-until-expiring \
  --preferred-challenges http \
  -d "$APP_HOSTNAME"; then
  cat >&2 <<EOF
certbot could not issue a certificate for $APP_HOSTNAME.

If this hostname uses sslip.io, Let's Encrypt may have hit the shared
sslip.io weekly quota. You can wait and rerun the installer, or point your
own DNS name at $PUBLIC_IP and rerun with:

  LIFE_ASSISTANT_DOMAIN=your.name.example bash deploy/install.sh

For release-test dry runs only, you can use Let's Encrypt staging with:

  LIFE_ASSISTANT_CERTBOT_STAGING=1 bash deploy/install.sh
EOF
  exit 1
fi
# Stage cert into /etc/life-assistant/tls/ for the service user. The renewal
# hook re-runs this script automatically every 60 days.
/etc/letsencrypt/renewal-hooks/deploy/life-assistant.sh

echo "==> first build"
sudo -u life-assistant "$REPO_DIR/deploy/update.sh" || true   # ok if already up to date
# update.sh exits 0 with no rebuild when already up to date; force a build
# on first install regardless so frontend/dist exists.
if [ ! -d "$REPO_DIR/frontend/dist" ]; then
  sudo -u life-assistant env HOME=/home/life-assistant \
    bash -c "cd $REPO_DIR/backend && $UV_BIN sync --frozen --python 3.11 --managed-python"
  sudo -u life-assistant bash -c "cd $REPO_DIR/backend && $REPO_DIR/backend/.venv/bin/alembic upgrade head"
  sudo -u life-assistant bash -c "cd $REPO_DIR/frontend && pnpm install --frozen-lockfile && pnpm build"
fi

SHOULD_SEED_LOGIN_PASS=0
if [ -f "$PENDING_PASSWORD_FILE" ]; then
  ensure_pending_login_password
  SHOULD_SEED_LOGIN_PASS=1
elif sudo -u life-assistant bash -c "set -a; source $ETC_DIR/life-assistant.env; set +a; cd $REPO_DIR/backend && $REPO_DIR/backend/.venv/bin/python -m app.users.needs_initial_password"; then
  ensure_pending_login_password
  SHOULD_SEED_LOGIN_PASS=1
fi

if [ "$SHOULD_SEED_LOGIN_PASS" = "1" ]; then
  echo "==> seed initial login password"
  # Migrations have run via update.sh / first-build branch above, so the
  # users table exists. The CLI creates the singleton row if missing.
  sudo -u life-assistant bash -c "set -a; source $ETC_DIR/life-assistant.env; set +a; cd $REPO_DIR/backend && $REPO_DIR/backend/.venv/bin/python -m app.users.set_password '$SEED_LOGIN_PASS'"
fi

echo "==> systemd units"
install -o root -g root -m 644 "$REPO_DIR/deploy/life-assistant.service"        /etc/systemd/system/life-assistant.service
install -o root -g root -m 644 "$REPO_DIR/deploy/life-assistant-update.service" /etc/systemd/system/life-assistant-update.service
install -o root -g root -m 644 "$REPO_DIR/deploy/life-assistant-backup.service" /etc/systemd/system/life-assistant-backup.service
install -o root -g root -m 644 "$REPO_DIR/deploy/life-assistant-backup.timer"   /etc/systemd/system/life-assistant-backup.timer
chmod +x "$REPO_DIR/deploy/update.sh" "$REPO_DIR/deploy/backup.sh" "$REPO_DIR/deploy/certbot-deploy.sh"

echo "==> sudoers"
install -o root -g root -m 440 "$REPO_DIR/deploy/sudoers.life-assistant" /etc/sudoers.d/life-assistant
visudo -c -q -f /etc/sudoers.d/life-assistant

echo "==> enable + start"
systemctl daemon-reload
systemctl enable --now life-assistant.service life-assistant-backup.timer
# certbot ships its own renewal timer; make sure it is active for cert refresh.
systemctl enable --now certbot.timer 2>/dev/null || true

echo
echo "==============================================================="
echo "  Life Assistant ready"
echo "  URL:  https://$APP_HOSTNAME/"
if [ -n "$SEED_LOGIN_PASS" ]; then
  echo "  Password: $SEED_LOGIN_PASS"
  echo "  (rotate later with:  make set-password PASSWORD=<new>)"
  rm -f "$PENDING_PASSWORD_FILE"
fi
echo "==============================================================="
echo
echo "Privacy notes:"
echo "  - Traffic is end-to-end TLS between your browser and this server."
case "$APP_HOSTNAME" in
  *.sslip.io)
    echo "  - DNS for $APP_HOSTNAME is served by sslip.io (sees lookups, not content)."
    ;;
  *)
    echo "  - DNS for $APP_HOSTNAME is served by the DNS provider for that domain."
    ;;
esac
echo "  - To swap in your own domain later, see deploy/README.md."
echo
echo "Logs: journalctl -u life-assistant -f"
