#!/usr/bin/env bash
set -euo pipefail

HA_ENV_FILE="${HA_ENV_FILE:-/etc/muxingplus-ha/ha.env}"
if [[ ! -f "$HA_ENV_FILE" ]]; then
  echo "Missing HA env file: $HA_ENV_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$HA_ENV_FILE"

: "${HA_CLUSTER_ID:?HA_CLUSTER_ID is required}"
: "${HA_NODE_ID:?HA_NODE_ID is required}"
: "${HA_REGION:?HA_REGION is required}"
: "${HA_DDB_TABLE:?HA_DDB_TABLE is required}"

HA_LEASE_TTL_SEC="${HA_LEASE_TTL_SEC:-15}"
HA_LOOP_INTERVAL_SEC="${HA_LOOP_INTERVAL_SEC:-3}"
HA_STATE_DIR="${HA_STATE_DIR:-/run/muxingplus-ha}"
HA_LOG_FILE="${HA_LOG_FILE:-/var/log/muxingplus-ha.log}"
HA_IPSEC_SERVICE="${HA_IPSEC_SERVICE:-ipsec}"
HA_PROMOTE_START_SERVICES="${HA_PROMOTE_START_SERVICES:-}"
HA_DEMOTE_STOP_SERVICES="${HA_DEMOTE_STOP_SERVICES:-}"
FLOW_SYNC_MODE="${FLOW_SYNC_MODE:-none}"        # none | conntrackd
SA_SYNC_MODE="${SA_SYNC_MODE:-none}"            # none | libreswan-no-sa-sync | strongswan-ha
HA_CONNTRACKD_SERVICE="${HA_CONNTRACKD_SERVICE:-conntrackd}"
HA_CONNTRACKD_COMMIT_ON_PROMOTE="${HA_CONNTRACKD_COMMIT_ON_PROMOTE:-true}"
HA_CONNTRACKD_RESYNC_ON_DEMOTE="${HA_CONNTRACKD_RESYNC_ON_DEMOTE:-true}"

ROLE_FILE="$HA_STATE_DIR/role.state"
LEASE_FILE="$HA_STATE_DIR/lease.json"

mkdir -p "$HA_STATE_DIR"

log() {
  local msg="$*"
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$msg" | tee -a "$HA_LOG_FILE" >/dev/null
}

set_role() {
  local role="$1"
  printf '%s\n' "$role" > "$ROLE_FILE"
}

get_role() {
  if [[ -f "$ROLE_FILE" ]]; then
    cat "$ROLE_FILE"
  else
    echo "unknown"
  fi
}

start_services() {
  local units="$1"
  [[ -z "$units" ]] && return 0
  for svc in $units; do
    systemctl start "$svc"
  done
}

stop_services() {
  local units="$1"
  [[ -z "$units" ]] && return 0
  for svc in $units; do
    systemctl stop "$svc" || true
  done
}

run_hook() {
  local hook="$1"
  [[ -z "$hook" ]] && return 0
  if [[ -x "$hook" ]]; then
    "$hook"
  else
    log "hook not executable or missing: $hook"
  fi
}

run_local_script_if_exists() {
  local script_path="$1"
  if [[ -x "$script_path" ]]; then
    "$script_path"
  else
    log "script missing or not executable: $script_path"
  fi
}
