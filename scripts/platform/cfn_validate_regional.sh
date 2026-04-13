#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <regional-manifest.json> [region-filter]"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$1"
REGION_FILTER="${2:-}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required"
  exit 1
fi

if [[ ! -f "$MANIFEST" ]]; then
  if [[ -f "$ROOT_DIR/$MANIFEST" ]]; then
    MANIFEST="$ROOT_DIR/$MANIFEST"
  else
    echo "Manifest not found: $MANIFEST"
    exit 1
  fi
fi

if [[ "$(jq -r '.netbox.global_sot // false' "$MANIFEST")" != "true" ]]; then
  echo "Manifest must set netbox.global_sot=true"
  exit 1
fi

if [[ "$(jq -r '.netbox.deploy_with_cloudformation // true' "$MANIFEST")" != "false" ]]; then
  echo "Manifest must set netbox.deploy_with_cloudformation=false"
  exit 1
fi

mapfile -t REGIONS < <(jq -r '.regions[].name' "$MANIFEST")
if [[ ${#REGIONS[@]} -eq 0 ]]; then
  echo "No regions found in manifest"
  exit 1
fi

for REGION in "${REGIONS[@]}"; do
  if [[ -n "$REGION_FILTER" && "$REGION" != "$REGION_FILTER" ]]; then
    continue
  fi

  echo
  echo "=== Validate region: $REGION ==="
  bash "$ROOT_DIR/scripts/cfn_validate_muxer.sh" "$REGION"
  bash "$ROOT_DIR/scripts/cfn_validate_vpn_headend.sh" "$REGION"
done
