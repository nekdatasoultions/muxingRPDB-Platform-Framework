#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEMPLATE_FILE="${1:-$REPO_ROOT/infra/cfn/vpn-headend-unit.yaml}"
REGION="${2:-us-east-1}"

host_path() {
  local path="$1"
  if command -v wslpath >/dev/null 2>&1; then
    wslpath -w "$path"
    return
  fi
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$path"
    return
  fi
  printf '%s\n' "$path"
}

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required"
  exit 1
fi

AWS_TEMPLATE_FILE="$(host_path "$TEMPLATE_FILE")"

aws cloudformation validate-template \
  --region "$REGION" \
  --template-body "file://$AWS_TEMPLATE_FILE" >/dev/null

echo "Template valid: $TEMPLATE_FILE ($REGION)"
