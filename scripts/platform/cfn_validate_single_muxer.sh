#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REGION="${1:-us-east-1}"

bash "$SCRIPT_DIR/cfn_validate.sh" "$REPO_ROOT/infra/cfn/muxer-single-asg.yaml" "$REGION"
