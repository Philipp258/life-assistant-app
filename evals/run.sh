#!/usr/bin/env bash
# Spin an ephemeral Life Assistant instance, run the onboarding eval against it,
# tear it down. Picks free ports, uses a temp data dir, deletes after.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v agent-browser >/dev/null 2>&1; then
  cat >&2 <<'EOF'
agent-browser CLI not found on PATH.

Install:
  npm i -g agent-browser
  agent-browser install

The skill is vendored at .claude/skills/agent-browser/SKILL.md;
the CLI itself still has to be installed locally.
EOF
  exit 1
fi

free_port() {
  python3 -c 'import socket; s=socket.socket(); s.bind(("",0)); print(s.getsockname()[1]); s.close()'
}

wait_for() {
  local url="$1" deadline=$((SECONDS + 60))
  until curl -fsS -o /dev/null --max-time 2 "$url"; do
    (( SECONDS > deadline )) && { echo "timeout waiting for $url" >&2; return 1; }
    sleep 1
  done
}

# Pull credentials + provider keys from the worktree .env. Port + data
# dir are overridden after sourcing so the eval never collides with
# the dev tab.
set -a
# shellcheck disable=SC1091
source .env
set +a

EVAL_DATA_DIR="$(mktemp -d -t life-assistant-eval-XXXXXX)"
BACKEND_PORT="$(free_port)"
FRONTEND_PORT="$(free_port)"
APP_URL="http://localhost:${FRONTEND_PORT}"
EVAL_PASSWORD="evalpw"

export LIFE_ASSISTANT_DATA_DIR="$EVAL_DATA_DIR"
export BACKEND_PORT FRONTEND_PORT
export SESSION_SECRET="$(openssl rand -hex 32)"

PIDS=()

cleanup() {
  local code=$?
  for pid in "${PIDS[@]}"; do
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  rm -rf "$EVAL_DATA_DIR"
  exit "$code"
}
trap cleanup EXIT INT TERM

echo "eval data dir: $EVAL_DATA_DIR"
echo "backend:  http://localhost:${BACKEND_PORT}"
echo "frontend: ${APP_URL}"

# Schema must exist before uvicorn lifespan tries to seed the user row.
( cd backend && uv run alembic upgrade head )

# Seed the singleton user row with a known password so the agent can log in.
( cd backend && uv run python -m app.users.set_password "$EVAL_PASSWORD" )

( cd backend && exec uv run uvicorn app.main:app --port "$BACKEND_PORT" ) &
PIDS+=($!)
( cd frontend && exec pnpm dev --port "$FRONTEND_PORT" ) &
PIDS+=($!)

wait_for "http://localhost:${BACKEND_PORT}/api/health"
wait_for "${APP_URL}"

PROMPT="$(sed -e "s|<APP_URL>|${APP_URL}|g" -e "s|<PASSWORD>|${EVAL_PASSWORD}|g" evals/onboarding.md)"
LOG="evals/runs/$(date +%Y%m%d-%H%M%S).jsonl"
mkdir -p evals/runs
echo "log: $LOG"

claude -p "$PROMPT" \
  --model sonnet \
  --permission-mode dontAsk \
  --allowedTools "Bash(agent-browser:*)" \
  --output-format stream-json --verbose --include-partial-messages \
  | tee "$LOG" \
  | jq -r '
    if .type=="assistant" then
      .message.content[]?
      | if .type=="text" then .text
        elif .type=="tool_use" then "→ [\(.name)] \(.input | tostring | .[0:200])"
        else empty end
    elif .type=="user" then
      .message.content[]?
      | select(.type=="tool_result")
      | "← \((.content // "") | tostring | .[0:200])"
    elif .type=="stream_event" then
      .event.delta?.text? // empty
    else empty end'
