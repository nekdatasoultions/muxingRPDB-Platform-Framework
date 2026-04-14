#!/usr/bin/env bash
set -euo pipefail

TABLE_NAME="${1:-muxingplus_ha_leases}"
REGION="${2:-us-east-1}"

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found"
  exit 1
fi

if aws dynamodb describe-table --region "$REGION" --table-name "$TABLE_NAME" >/dev/null 2>&1; then
  echo "Table already exists: $TABLE_NAME"
  exit 0
fi

aws dynamodb create-table \
  --region "$REGION" \
  --table-name "$TABLE_NAME" \
  --attribute-definitions AttributeName=cluster_id,AttributeType=S \
  --key-schema AttributeName=cluster_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST >/dev/null

aws dynamodb wait table-exists --region "$REGION" --table-name "$TABLE_NAME"
echo "Created table: $TABLE_NAME in $REGION"
