#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/ha-common.sh"

log "leader-loop: starting"

while true; do
  desired_role="$($SCRIPT_DIR/ha-role.sh)"
  current_role="$(get_role)"

  if [[ "$desired_role" != "$current_role" ]]; then
    if [[ "$desired_role" == "active" ]]; then
      "$SCRIPT_DIR/ha-promote.sh"
    else
      "$SCRIPT_DIR/ha-demote.sh"
    fi
  fi

  sleep "$HA_LOOP_INTERVAL_SEC"
done
