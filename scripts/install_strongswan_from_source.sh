#!/usr/bin/env bash
set -euo pipefail

# Keep the runtime package contract stable for head-end bootstrap while the
# framework-level script remains organized under scripts/platform.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/platform/install_strongswan_from_source.sh" "$@"
