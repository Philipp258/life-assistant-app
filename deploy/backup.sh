#!/usr/bin/env bash
# Daily snapshot of /var/lib/life-assistant/data: SQLite DB + markdown
# (core memory, knowledge, user-installed skills). Keeps last 7.
# Runs as root via life-assistant-backup.service.
set -euo pipefail

DATA_DIR=${LIFE_ASSISTANT_DATA_DIR:-/var/lib/life-assistant/data}
DEST=${LIFE_ASSISTANT_BACKUP_DIR:-/var/lib/life-assistant/backups}
mkdir -p "$DEST"

STAMP=$(date +%F-%H%M%S)
DB_BASENAME=life_assistant.db
DB="$DATA_DIR/$DB_BASENAME"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/stage"
mkdir -p "$STAGE"

# Stage non-database data first. The DB is copied below through SQLite's
# backup API so the archive never captures inconsistent WAL state.
tar -cf - \
  --exclude='life_assistant.db' \
  --exclude='life_assistant.db-shm' \
  --exclude='life_assistant.db-wal' \
  -C "$DATA_DIR" . \
  | tar -xf - -C "$STAGE"

# Hot-copy the SQLite DB via the official .backup API so we get a
# transactionally-consistent snapshot regardless of in-flight writes.
if [ -f "$DB" ]; then
  sqlite3 "$DB" ".backup $STAGE/$DB_BASENAME"
fi

# Tar the staged data + consistent DB snapshot.
ARCHIVE="$DEST/life-assistant-$STAMP.tar.gz"
tar -czf "$ARCHIVE" -C "$STAGE" .

ls -1t "$DEST"/life-assistant-*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm --
