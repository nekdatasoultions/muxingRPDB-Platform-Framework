#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_FILE="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/cfn/vpn-headend-unit.yaml}"
REGION="${2:-us-east-1}"

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required"
  exit 1
fi

aws cloudformation validate-template \
  --region "$REGION" \
  --template-body "file://$TEMPLATE_FILE" >/dev/null

echo "Template valid: $TEMPLATE_FILE ($REGION)"
