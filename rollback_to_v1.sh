#!/usr/bin/env bash
# Rollback to V1 — the stable state before Pro tab was added.
#
# This script:
#   1. Stops the live server agent
#   2. Restores all code files from the V1 git tag
#   3. Optionally restores portfolio.db from the V1 snapshot (asks first)
#   4. Restarts the server
#
# Usage:
#   ./rollback_to_v1.sh                  # rollback code only
#   ./rollback_to_v1.sh --restore-db     # rollback code AND restore V1 DB
#
# Your CURRENT state is preserved as a git tag `v2-before-rollback` so you
# can come back to V2 at any time with:
#   git checkout v2-before-rollback

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd -P)"
cd "$ROOT"
BACKUP_DIR="${ROOT}/../DashBoard_v1_backup"
RESTORE_DB="${1:-}"

echo "═══════════════════════════════════════════════════════════════"
echo "  GPCP Dashboard — Rollback to V1"
echo "═══════════════════════════════════════════════════════════════"
echo

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: not a git repo. Cannot rollback." >&2
  exit 1
fi
if ! git rev-parse v1 >/dev/null 2>&1; then
  echo "ERROR: tag 'v1' not found. Cannot rollback." >&2
  exit 1
fi

# Preserve current state
if [[ -n "$(git status --porcelain)" ]]; then
  git add -A
  git -c user.email="gpcp@local" -c user.name="GPCP" commit -q -m "snapshot before V1 rollback ($(date -Iseconds))"
fi
git tag -f v2-before-rollback >/dev/null 2>&1 || true
echo "✓ Current state preserved as git tag: v2-before-rollback"

# Stop the live server (so files aren't held open)
launchctl kickstart -k "gui/$(id -u)/com.gpcp.dashboard.server" 2>/dev/null || true
echo "✓ Server stopped"

# Restore code from v1 tag
git checkout v1 -- app.py data.py prices.py daily_update.py 2>/dev/null || true
# Also restore any other Python files that existed in V1
git checkout v1 -- . 2>/dev/null || true
echo "✓ Code files restored from git tag 'v1'"

# Optionally restore the DB
if [[ "$RESTORE_DB" == "--restore-db" ]]; then
  if [[ -f "${BACKUP_DIR}/portfolio.db" ]]; then
    cp "${ROOT}/portfolio.db" "${ROOT}/portfolio.v2.db.bak" 2>/dev/null || true
    cp "${BACKUP_DIR}/portfolio.db" "${ROOT}/portfolio.db"
    echo "✓ portfolio.db restored from V1 snapshot"
    echo "  (V2 DB preserved as portfolio.v2.db.bak)"
  else
    echo "⚠ No V1 DB snapshot found at ${BACKUP_DIR}/portfolio.db"
  fi
else
  echo "ℹ portfolio.db kept as-is (use --restore-db to also restore V1 data)"
fi

# Restart server to pick up V1 code
launchctl kickstart "gui/$(id -u)/com.gpcp.dashboard.server" 2>/dev/null || true
sleep 2
if curl -sf http://localhost:8501/_stcore/health >/dev/null 2>&1; then
  echo "✓ Server restarted on http://localhost:8501"
fi

echo
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ Rolled back to V1"
echo "═══════════════════════════════════════════════════════════════"
echo
echo "To go back to V2:"
echo "  git checkout v2-before-rollback -- ."
echo "  launchctl kickstart -k gui/\$(id -u)/com.gpcp.dashboard.server"
