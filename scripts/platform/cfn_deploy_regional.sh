#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <regional-manifest.json> [region-filter] [--plan]"
  echo "Example:"
  echo "  $0 config/regional-deployment.example.json"
  echo "  $0 config/regional-deployment.example.json us-east-1"
  echo "  $0 config/regional-deployment.example.json --plan"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MANIFEST="$1"
REGION_FILTER=""
PLAN_ONLY="false"

for arg in "${@:2}"; do
  if [[ "$arg" == "--plan" ]]; then
    PLAN_ONLY="true"
  else
    REGION_FILTER="$arg"
  fi
done

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required"
  exit 1
fi

if [[ ! -f "$MANIFEST" ]]; then
  if [[ -f "$REPO_ROOT/$MANIFEST" ]]; then
    MANIFEST="$REPO_ROOT/$MANIFEST"
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
  echo "=== Region: $REGION ==="

  MUXER_ENABLED="$(jq -r --arg r "$REGION" '.regions[] | select(.name==$r) | .muxer.enabled // false' "$MANIFEST")"
  if [[ "$MUXER_ENABLED" == "true" ]]; then
    MUXER_STACK="$(jq -r --arg r "$REGION" '.regions[] | select(.name==$r) | .muxer.stack_name' "$MANIFEST")"
    MUXER_PARAMS="$(jq -r --arg r "$REGION" '.regions[] | select(.name==$r) | .muxer.params_file' "$MANIFEST")"
    [[ "$MUXER_PARAMS" = /* ]] || MUXER_PARAMS="$REPO_ROOT/$MUXER_PARAMS"

    if [[ "$PLAN_ONLY" == "true" ]]; then
      echo "[PLAN] Muxer: region=$REGION stack=$MUXER_STACK params=$MUXER_PARAMS"
    else
      echo "[DEPLOY] Muxer: region=$REGION stack=$MUXER_STACK"
      bash "$SCRIPT_DIR/cfn_deploy_muxer.sh" "$MUXER_STACK" "$MUXER_PARAMS" "$REGION"
    fi
  else
    echo "[SKIP] Muxer disabled for $REGION"
  fi

  mapfile -t UNIT_ROWS < <(jq -cr --arg r "$REGION" '.regions[] | select(.name==$r) | .vpn_headend_units[]?' "$MANIFEST")
  if [[ ${#UNIT_ROWS[@]} -eq 0 ]]; then
    echo "[SKIP] No VPN headend units configured for $REGION"
    continue
  fi

  for row in "${UNIT_ROWS[@]}"; do
    STACK_NAME="$(jq -r '.stack_name' <<<"$row")"
    PARAMS_FILE="$(jq -r '.params_file' <<<"$row")"
    [[ "$PARAMS_FILE" = /* ]] || PARAMS_FILE="$REPO_ROOT/$PARAMS_FILE"

    if [[ "$PLAN_ONLY" == "true" ]]; then
      echo "[PLAN] VPN unit: region=$REGION stack=$STACK_NAME params=$PARAMS_FILE"
    else
      echo "[DEPLOY] VPN unit: region=$REGION stack=$STACK_NAME"
      bash "$SCRIPT_DIR/cfn_deploy_vpn_headend.sh" "$STACK_NAME" "$PARAMS_FILE" "$REGION"
    fi
  done
done
