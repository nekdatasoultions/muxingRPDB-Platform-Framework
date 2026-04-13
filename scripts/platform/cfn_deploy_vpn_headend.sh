#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <stack-name> <parameters-json> [region]"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_NAME="$1"
PARAM_FILE="$2"
REGION="${3:-us-east-1}"

bash "$ROOT_DIR/scripts/cfn_deploy.sh" \
  "$STACK_NAME" \
  "$PARAM_FILE" \
  "$REGION" \
  "$ROOT_DIR/cfn/vpn-headend-unit.yaml"
