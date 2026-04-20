#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/ha-common.sh"

if [[ "$FLOW_SYNC_MODE" != "conntrackd" ]]; then
  exit 0
fi

if ! command -v conntrackd >/dev/null 2>&1; then
  log "conntrack demote: conntrackd binary not found"
  exit 0
fi

if [[ "$HA_CONNTRACKD_RESYNC_ON_DEMOTE" == "true" ]]; then
  conntrackd -s >/dev/null 2>&1 || true
  log "conntrack demote: status sync check executed (conntrackd -s)"
fi
