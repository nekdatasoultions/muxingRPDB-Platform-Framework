#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 s3://bucket/path/muxer-recovery-lambda.zip [source_dir]"
  exit 1
fi

S3_URI="$1"
DEFAULT_SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../muxer/runtime-package/cloudwatch-muxer-recovery" && pwd)"
SOURCE_DIR="${2:-$DEFAULT_SOURCE_DIR}"
SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
TMP_DIR="$SOURCE_DIR/.package-tmp"
ZIP_PATH="$TMP_DIR/muxer-recovery-lambda.zip"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

to_host_path() {
  if command -v wslpath >/dev/null 2>&1; then
    wslpath -w "$1"
  elif command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$1"
  else
    echo "$1"
  fi
}

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required"
  exit 1
fi

if [[ ! -f "$SOURCE_DIR/lambda_function.py" ]]; then
  echo "lambda_function.py not found under $SOURCE_DIR"
  exit 1
fi

python3 - "$SOURCE_DIR" "$ZIP_PATH" <<'PY'
from pathlib import Path
import sys
import zipfile

source_dir = Path(sys.argv[1]).resolve()
zip_path = Path(sys.argv[2]).resolve()
zip_path.parent.mkdir(parents=True, exist_ok=True)
if zip_path.exists():
    zip_path.unlink()
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write(source_dir / "lambda_function.py", "lambda_function.py")
PY

aws s3 cp "$(to_host_path "$ZIP_PATH")" "$S3_URI"
echo "Uploaded muxer recovery lambda package to $S3_URI"
