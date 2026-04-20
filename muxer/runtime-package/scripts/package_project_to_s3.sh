#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 s3://bucket/path/rpdb-muxer-runtime-bundle.zip [project_root]"
  exit 1
fi

S3_URI="$1"
PROJECT_ROOT="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
TMP_DIR="$PROJECT_ROOT/.package-tmp"
TMP_ZIP="$TMP_DIR/rpdb-muxer-runtime-bundle.zip"

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

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required"
  exit 1
fi

python3 - "$PROJECT_ROOT" "$TMP_ZIP" <<'PY'
from pathlib import Path
import sys
import zipfile

project_root = Path(sys.argv[1]).resolve()
tmp_zip = Path(sys.argv[2]).resolve()
exclude_parts = {".git", ".vscode", "__pycache__", "build"}
tmp_zip.parent.mkdir(parents=True, exist_ok=True)

if tmp_zip.exists():
    tmp_zip.unlink()

with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in project_root.rglob("*"):
        rel = path.relative_to(project_root)
        if any(part in exclude_parts for part in rel.parts):
            continue
        if path.is_file() and not path.name.endswith(".pyc"):
            zf.write(path, rel.as_posix())
PY

aws s3 cp "$(to_host_path "$TMP_ZIP")" "$S3_URI"
echo "Uploaded project package to $S3_URI"
