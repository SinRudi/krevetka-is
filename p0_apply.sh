#!/bin/bash
# Apply the P0 hardening patch with a full rollback backup.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_FILE="$APP_DIR/p0_hardening.patch"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/p0_$STAMP"

if [ ! -f "$PATCH_FILE" ]; then
    echo "Patch not found: $PATCH_FILE" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# 1. WAL-safe database copy (never plain cp on a live WAL database).
if [ -f "$APP_DIR/sushi.db" ]; then
    python3 - "$APP_DIR/sushi.db" "$BACKUP_DIR/sushi.db" <<'PY'
import sqlite3
import sys

src = sqlite3.connect(sys.argv[1], timeout=10)
dst = sqlite3.connect(sys.argv[2])
try:
    with dst:
        src.backup(dst)
finally:
    dst.close()
    src.close()
PY
    echo "DB backup: $BACKUP_DIR/sushi.db"
fi

# 2. Code backup (everything except the database itself).
tar czf "$BACKUP_DIR/code.tar.gz" -C "$APP_DIR" \
    --exclude='./sushi.db' --exclude='./sushi.db-wal' --exclude='./sushi.db-shm' \
    --exclude='./backups' --exclude='./__pycache__' --exclude='./*.pyc' .
echo "Code backup: $BACKUP_DIR/code.tar.gz"

# 3. Dry-run, then apply.
cd "$APP_DIR"
patch -p1 --dry-run < "$PATCH_FILE"
patch -p1 < "$PATCH_FILE"

chmod 750 backup.sh run.py 2>/dev/null || true

echo
echo "P0 hardening applied."
echo "Rollback:"
echo "  tar xzf '$BACKUP_DIR/code.tar.gz' -C '$APP_DIR'"
echo "  python3 - '$BACKUP_DIR/sushi.db' '$APP_DIR/sushi.db' <<'PY'"
echo "      import sqlite3, sys"
echo "      s = sqlite3.connect(sys.argv[1], timeout=10); d = sqlite3.connect(sys.argv[2])"
echo "      with d: s.backup(d)"
echo "  PY"
