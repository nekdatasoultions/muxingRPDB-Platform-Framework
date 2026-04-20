#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/ha-common.sh"

if ! command -v aws >/dev/null 2>&1; then
  log "aws CLI not found"
  echo standby
  exit 0
fi

now="$(date +%s)"
exp="$((now + HA_LEASE_TTL_SEC))"

key_json=$(cat <<EOF
{"cluster_id":{"S":"$HA_CLUSTER_ID"}}
EOF
)

attrs_json=$(cat <<EOF
{":me":{"S":"$HA_NODE_ID"},":exp":{"N":"$exp"},":now":{"N":"$now"}}
EOF
)

set +e
lease_out=$(aws dynamodb update-item \
  --region "$HA_REGION" \
  --cli-connect-timeout 2 \
  --cli-read-timeout 4 \
  --table-name "$HA_DDB_TABLE" \
  --key "$key_json" \
  --update-expression "SET holder=:me, expires_at=:exp, updated_at=:now" \
  --condition-expression "attribute_not_exists(holder) OR holder = :me OR expires_at < :now" \
  --expression-attribute-values "$attrs_json" \
  --return-values ALL_NEW \
  --output json 2>&1)
rc=$?
set -e

if [[ $rc -eq 0 ]]; then
  printf '%s\n' "$lease_out" > "$LEASE_FILE"
  echo active
  exit 0
fi

# Conditional-check failure means another node currently holds the lease.
if grep -q "ConditionalCheckFailedException" <<<"$lease_out"; then
  echo standby
  exit 0
fi

# For transient API/network errors, preserve current role to avoid flapping.
current_role="$(get_role)"
if [[ "$current_role" == "active" || "$current_role" == "standby" ]]; then
  log "ha-role: lease update error, preserving current role=$current_role"
  echo "$current_role"
else
  log "ha-role: lease update error, no prior role; defaulting standby"
  echo standby
fi
exit 0
