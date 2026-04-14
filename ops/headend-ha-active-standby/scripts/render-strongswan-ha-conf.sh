#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-/etc/muxingplus-ha/ha-sync.env}"
OUT_FILE="${2:-/etc/strongswan.d/charon/ha.conf}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE"
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

: "${HA_SYNC_LOCAL_IP:?HA_SYNC_LOCAL_IP is required}"
: "${HA_SYNC_REMOTE_IP:?HA_SYNC_REMOTE_IP is required}"
: "${HA_SYNC_SECRET:?HA_SYNC_SECRET is required}"

cat >"$OUT_FILE" <<EOF
charon {
  plugins {
    ha {
      local = $HA_SYNC_LOCAL_IP
      remote = $HA_SYNC_REMOTE_IP
      secret = $HA_SYNC_SECRET
      segment_count = 1
      monitor = yes
      heartbeat_delay = 1000
      heartbeat_timeout = 2100
      resync = yes
      fifo_interface = yes
    }
  }
}
EOF

chmod 600 "$OUT_FILE"
echo "Rendered $OUT_FILE"
