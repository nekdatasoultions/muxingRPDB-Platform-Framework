#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${1:-/opt/muxer}"
TARGET_ROOT="${2:-/etc/muxer}"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

if [[ ! -d "$PROJECT_ROOT/src" || ! -d "$PROJECT_ROOT/config" || ! -d "$PROJECT_ROOT/systemd" ]]; then
  echo "Expected RPDB muxer runtime package layout under $PROJECT_ROOT"
  exit 1
fi

mkdir -p "$TARGET_ROOT"

if [[ -f "$PROJECT_ROOT/scripts/install_deps_amzn.sh" ]]; then
  if command -v dnf >/dev/null 2>&1 || command -v yum >/dev/null 2>&1; then
    bash "$PROJECT_ROOT/scripts/install_deps_amzn.sh"
  fi
fi

for dir in config docs scripts src systemd; do
  rm -rf "$TARGET_ROOT/$dir"
  cp -a "$PROJECT_ROOT/$dir" "$TARGET_ROOT/$dir"
done

# Windows-authored bundles can arrive with CRLF endings; normalize the
# runtime/config tree on the Linux host before services consume it.
find "$TARGET_ROOT" -type f \
  \( -name "*.sh" -o -name "*.py" -o -name "*.env" -o -name "*.yaml" -o -name "*.yml" -o -name "*.conf" -o -name "*.secrets" -o -name "*.service" \) \
  -exec sed -i 's/\r$//' {} +

install -m 0644 "$TARGET_ROOT/systemd/muxer.service" /etc/systemd/system/muxer.service

if [[ -f "$TARGET_ROOT/systemd/muxer-trace.service" ]]; then
  install -m 0644 "$TARGET_ROOT/systemd/muxer-trace.service" /etc/systemd/system/muxer-trace.service
fi

if [[ -f "$TARGET_ROOT/systemd/ike-nat-bridge.service" ]]; then
  install -m 0644 "$TARGET_ROOT/systemd/ike-nat-bridge.service" /etc/systemd/system/ike-nat-bridge.service
fi

find "$TARGET_ROOT/scripts" -type f -name "*.sh" -exec chmod 0755 {} \;
find "$TARGET_ROOT/src" -type f -name "*.py" -exec chmod 0755 {} \;

systemctl daemon-reload

echo "Installed RPDB muxer runtime under $TARGET_ROOT"
echo "Next steps:"
echo "  1. place customer/module config under $TARGET_ROOT/config"
echo "  2. systemctl enable muxer.service"
echo "  3. systemctl start muxer.service"
