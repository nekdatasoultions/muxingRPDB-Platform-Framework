#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/ha-common.sh"

log "promote: starting"

if [[ -n "${HA_EIP_ALLOC_ID:-}" && -n "${HA_ENI_ID:-}" ]]; then
  if command -v aws >/dev/null 2>&1; then
    aws ec2 associate-address \
      --region "$HA_REGION" \
      --allocation-id "$HA_EIP_ALLOC_ID" \
      --network-interface-id "$HA_ENI_ID" \
      --allow-reassociation >/dev/null
    log "promote: associated EIP $HA_EIP_ALLOC_ID to ENI $HA_ENI_ID"
  else
    log "promote: aws CLI missing, skipping EIP association"
  fi
fi

run_local_script_if_exists "$SCRIPT_DIR/ha-conntrack-promote.sh"

systemctl start "$HA_IPSEC_SERVICE"
log "promote: started $HA_IPSEC_SERVICE"

if [[ "$HA_IPSEC_SERVICE" == "strongswan" ]] && command -v swanctl >/dev/null 2>&1; then
  swanctl --load-all
  log "promote: loaded strongSwan connection state via swanctl --load-all"
fi

if [[ "$SA_SYNC_MODE" == "libreswan-no-sa-sync" ]]; then
  log "promote: SA sync mode is libreswan-no-sa-sync (tunnels may re-establish after failover)"
elif [[ "$SA_SYNC_MODE" == "strongswan-ha" ]]; then
  log "promote: SA sync mode is strongswan-ha (state sync handled by charon ha plugin)"
fi

start_services "$HA_PROMOTE_START_SERVICES"
run_hook "${HA_PROMOTE_HOOK:-}"

set_role active
log "promote: node is ACTIVE"
