#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/ha-common.sh"

echo "=== Muxingplus HA Status ==="
echo "cluster_id: $HA_CLUSTER_ID"
echo "node_id:    $HA_NODE_ID"
echo "region:     $HA_REGION"
echo "table:      $HA_DDB_TABLE"
echo "role:       $(get_role)"
echo "flow_sync:  $FLOW_SYNC_MODE"
echo "sa_sync:    $SA_SYNC_MODE"
echo

if [[ -f "$LEASE_FILE" ]]; then
  echo "--- lease file ---"
  cat "$LEASE_FILE"
  echo
fi

echo "--- ipsec service ---"
systemctl status "$HA_IPSEC_SERVICE" --no-pager || true

echo
if [[ -n "${HA_EIP_ALLOC_ID:-}" ]]; then
  echo "--- eip association (configured) ---"
  echo "allocation_id: $HA_EIP_ALLOC_ID"
  echo "eni_id:        ${HA_ENI_ID:-unset}"
fi
