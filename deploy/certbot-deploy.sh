#!/usr/bin/env bash
# Copies the renewed Let's Encrypt cert into /etc/life-assistant/tls/ where the
# life-assistant service user can read it, then restarts uvicorn so it picks
# up the new key. Invoked by certbot via /etc/letsencrypt/renewal-hooks/deploy/
# on every renewal, and once by install.sh on first issuance.
set -euo pipefail

LINEAGE="${RENEWED_LINEAGE:-}"
if [ -z "$LINEAGE" ]; then
  LINEAGE=$(find /etc/letsencrypt/live -mindepth 1 -maxdepth 1 -type d ! -name README 2>/dev/null | head -n1)
fi
if [ -z "$LINEAGE" ] || [ ! -f "$LINEAGE/fullchain.pem" ]; then
  echo "certbot-deploy: no cert lineage found under /etc/letsencrypt/live" >&2
  exit 1
fi

TLS_DIR=/etc/life-assistant/tls
install -d -o life-assistant -g life-assistant -m 750 "$TLS_DIR"
install -o life-assistant -g life-assistant -m 640 "$LINEAGE/fullchain.pem" "$TLS_DIR/cert.pem"
install -o life-assistant -g life-assistant -m 640 "$LINEAGE/privkey.pem"   "$TLS_DIR/key.pem"

if systemctl is-enabled --quiet life-assistant.service 2>/dev/null \
  || systemctl is-active --quiet life-assistant.service 2>/dev/null; then
  systemctl try-restart life-assistant.service || true
fi
