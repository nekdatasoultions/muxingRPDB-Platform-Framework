#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <stack-name> <parameters-json> [region]"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STACK_NAME="$1"
PARAM_FILE="$2"
REGION="${3:-us-east-1}"

bash "$SCRIPT_DIR/cfn_deploy.sh" \
  "$STACK_NAME" \
  "$PARAM_FILE" \
  "$REGION" \
  "$REPO_ROOT/infra/cfn/muxer-single-asg.yaml"
