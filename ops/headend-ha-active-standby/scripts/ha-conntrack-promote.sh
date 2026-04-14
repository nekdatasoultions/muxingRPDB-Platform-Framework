#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/ha-common.sh"

if [[ "$FLOW_SYNC_MODE" != "conntrackd" ]]; then
  exit 0
fi

if ! command -v conntrackd >/dev/null 2>&1; then
  log "conntrack promote: conntrackd binary not found"
  exit 0
fi

systemctl start "$HA_CONNTRACKD_SERVICE" || true
log "conntrack promote: ensured $HA_CONNTRACKD_SERVICE is running"

if [[ "$HA_CONNTRACKD_COMMIT_ON_PROMOTE" == "true" ]]; then
  conntrackd -c || true
  log "conntrack promote: commit attempted (conntrackd -c)"
fi
