#!/usr/bin/env bash
# Life Assistant self-update. Runs as the `life-assistant` user via life-assistant-update.service.
# Pulls the configured branch (default main), installs deps, runs migrations,
# builds frontend, restarts the legacy life-assistant service.
set -euo pipefail

# Tell pnpm we're non-interactive so it won't bail on "Aborted removal of
# modules directory due to no TTY" when the lockfile changes.
export CI=true

REPO=/opt/life-assistant
PROJECT_VENV=$REPO/backend/.venv     # uv-managed project deps
UV_BIN=${LIFE_ASSISTANT_UV_BIN:-/home/life-assistant/.local/bin/uv}

if [ ! -x "$UV_BIN" ]; then
  echo "uv not found at $UV_BIN; rerun deploy/install.sh to install standalone uv" >&2
  exit 1
fi

export HOME=/home/life-assistant

REF=main
if [ -r /etc/life-assistant/deploy.env ]; then
  # shellcheck disable=SC1091
  source /etc/life-assistant/deploy.env
fi
REF="${REF:-main}"

cd "$REPO"

git fetch --quiet origin "$REF"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$REF")
if [ "$LOCAL" = "$REMOTE" ]; then
  echo "already up to date ($LOCAL on $REF)"
  exit 0
fi
git reset --hard "origin/$REF"

cd "$REPO/backend"
"$UV_BIN" python install 3.11 --managed-python
"$UV_BIN" sync --frozen --python 3.11 --managed-python
"$PROJECT_VENV/bin/alembic" upgrade head

cd "$REPO/frontend"
pnpm install --frozen-lockfile
# Stamp the build with the deployed commit SHA so the running PWA can
# spot "you're on an older shell than what the server is serving" and
# reload itself. See frontend/src/lib/build-check.ts and issue #173.
export LIFE_ASSISTANT_BUILD_ID="$REMOTE"
pnpm build

sudo /usr/bin/systemctl restart life-assistant.service
echo "deployed $REMOTE"
