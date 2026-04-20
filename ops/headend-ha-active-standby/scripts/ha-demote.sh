#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/ha-common.sh"

HA_DEMOTE_STOP_IPSEC="${HA_DEMOTE_STOP_IPSEC:-true}"

log "demote: starting"

run_local_script_if_exists "$SCRIPT_DIR/ha-conntrack-demote.sh"

stop_services "$HA_DEMOTE_STOP_SERVICES"

if [[ "$HA_DEMOTE_STOP_IPSEC" == "true" ]]; then
  systemctl stop "$HA_IPSEC_SERVICE" || true
  log "demote: stopped $HA_IPSEC_SERVICE"
fi

if [[ "$SA_SYNC_MODE" == "libreswan-no-sa-sync" ]]; then
  log "demote: SA sync mode is libreswan-no-sa-sync"
elif [[ "$SA_SYNC_MODE" == "strongswan-ha" ]]; then
  log "demote: SA sync mode is strongswan-ha"
fi

run_hook "${HA_DEMOTE_HOOK:-}"

set_role standby
log "demote: node is STANDBY"
