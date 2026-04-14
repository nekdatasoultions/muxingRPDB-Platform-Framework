#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 s3://bucket/path/muxer-recovery-lambda.zip [source_dir]"
  exit 1
fi

S3_URI="$1"
DEFAULT_SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../muxer/runtime-package/cloudwatch-muxer-recovery" && pwd)"
SOURCE_DIR="${2:-$DEFAULT_SOURCE_DIR}"
TMP_DIR="$(mktemp -d)"
ZIP_PATH="$TMP_DIR/muxer-recovery-lambda.zip"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required"
  exit 1
fi

if ! command -v zip >/dev/null 2>&1; then
  echo "zip is required"
  exit 1
fi

if [[ ! -f "$SOURCE_DIR/lambda_function.py" ]]; then
  echo "lambda_function.py not found under $SOURCE_DIR"
  exit 1
fi

pushd "$SOURCE_DIR" >/dev/null
zip -q "$ZIP_PATH" lambda_function.py
popd >/dev/null

aws s3 cp "$ZIP_PATH" "$S3_URI"
echo "Uploaded muxer recovery lambda package to $S3_URI"
