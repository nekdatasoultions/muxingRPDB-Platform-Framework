#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGION="${1:-us-east-1}"

bash "$ROOT_DIR/scripts/cfn_validate.sh" "$ROOT_DIR/cfn/muxer-single-asg.yaml" "$REGION"
