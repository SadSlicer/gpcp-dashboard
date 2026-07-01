#!/usr/bin/env bash
# Install/uninstall the two GPCP launchd agents:
#   1. com.gpcp.dashboard.daily   — cron at 18:00 Mon–Fri (price fetch + save)
#   2. com.gpcp.dashboard.server  — keeps the Streamlit server running at login
#
# Usage:
#   ./install_launchd.sh            # install + load both
#   ./install_launchd.sh uninstall  # stop + remove both
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd -P)"
DEST_DIR="${HOME}/Library/LaunchAgents"

AGENTS=(
  "com.gpcp.dashboard.daily"
  "com.gpcp.dashboard.server"
  "com.gpcp.dashboard.compositions"
)

cmd="${1:-install}"

if [[ "$cmd" == "uninstall" ]]; then
  for label in "${AGENTS[@]}"; do
    dest="${DEST_DIR}/${label}.plist"
    if [[ -f "$dest" ]]; then
      launchctl unload "$dest" 2>/dev/null || true
      rm -f "$dest"
      echo "✓ Removed $dest"
    fi
  done
  echo
  echo "All GPCP launchd agents removed."
  exit 0
fi

if [[ ! -f "${ROOT}/.venv/bin/python" ]]; then
  echo "ERROR: ${ROOT}/.venv/bin/python not found. Run ./run.sh once first to create the venv." >&2
  exit 1
fi
if [[ ! -f "${ROOT}/.venv/bin/streamlit" ]]; then
  echo "ERROR: ${ROOT}/.venv/bin/streamlit not found. Install deps with ./run.sh first." >&2
  exit 1
fi

mkdir -p "$DEST_DIR"

# Free port 8501 if anything else is holding it (e.g. a Streamlit started by hand)
if lsof -nP -iTCP:8501 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "⚠ Port 8501 is busy — stopping the existing process so the server agent can take over:"
  lsof -nP -iTCP:8501 -sTCP:LISTEN | awk 'NR>1 {print "  pid="$2, $1}'
  lsof -nP -iTCP:8501 -sTCP:LISTEN -t | xargs -r kill -TERM
  # give it a moment to release the port
  for _ in 1 2 3 4 5; do
    sleep 1
    lsof -nP -iTCP:8501 -sTCP:LISTEN >/dev/null 2>&1 || break
  done
fi

for label in "${AGENTS[@]}"; do
  src="${ROOT}/${label}.plist"
  dest="${DEST_DIR}/${label}.plist"
  if [[ ! -f "$src" ]]; then
    echo "ERROR: source plist not found: $src" >&2
    exit 1
  fi
  # Substitute %ROOT% with the real absolute path
  sed "s|%ROOT%|${ROOT}|g" "$src" > "$dest"
  # Reload (unload first to pick up changes)
  launchctl unload "$dest" 2>/dev/null || true
  launchctl load "$dest"
  echo "✓ Installed launchd agent: $label"
  echo "    Plist: $dest"
done

echo
echo "──────────────────────────────────────────────────────────────"
echo "✓ All set. The dashboard will now:"
echo "    • auto-start at every login                  → http://localhost:8501"
echo "    • auto-fetch + historize prices Mon–Fri @18h → daily_update.log"
echo "    • auto-restart if streamlit ever crashes"
echo "──────────────────────────────────────────────────────────────"
echo
echo "Verify:                  launchctl list | grep gpcp"
echo "Server logs:             tail -f ${ROOT}/server.stdout.log"
echo "Daily-update logs:       tail -f ${ROOT}/daily_update.log"
echo "Trigger daily job now:   launchctl start com.gpcp.dashboard.daily"
echo "Restart server now:      launchctl kickstart -k gui/\$(id -u)/com.gpcp.dashboard.server"
echo "Uninstall everything:    ./install_launchd.sh uninstall"
