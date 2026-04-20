#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${1:-/opt/muxingplus-ha}"
SCRIPT_SRC="$PROJECT_ROOT/ops/headend-ha-active-standby/scripts"
UNIT_SRC="$PROJECT_ROOT/ops/headend-ha-active-standby/systemd/muxingplus-ha.service"
CONNTRACKD_EXAMPLE="$PROJECT_ROOT/config/conntrackd/conntrackd.conf.ftfw.example"
STRONGSWAN_HA_EXAMPLE="$PROJECT_ROOT/config/strongswan/charon-ha.conf.example"
STRONGSWAN_HA_ENV_EXAMPLE="$PROJECT_ROOT/config/strongswan/ha-sync.env.example"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

mkdir -p /etc/muxingplus-ha
if [[ ! -f /etc/muxingplus-ha/ha.env ]]; then
  cp "$PROJECT_ROOT/config/ha.env.example" /etc/muxingplus-ha/ha.env
fi

install -m 0755 "$SCRIPT_SRC/ha-common.sh" /usr/local/sbin/ha-common.sh
install -m 0755 "$SCRIPT_SRC/ha-role.sh" /usr/local/sbin/ha-role.sh
install -m 0755 "$SCRIPT_SRC/ha-promote.sh" /usr/local/sbin/ha-promote.sh
install -m 0755 "$SCRIPT_SRC/ha-demote.sh" /usr/local/sbin/ha-demote.sh
install -m 0755 "$SCRIPT_SRC/ha-conntrack-promote.sh" /usr/local/sbin/ha-conntrack-promote.sh
install -m 0755 "$SCRIPT_SRC/ha-conntrack-demote.sh" /usr/local/sbin/ha-conntrack-demote.sh
install -m 0755 "$SCRIPT_SRC/ha-leader-loop.sh" /usr/local/sbin/ha-leader-loop.sh
install -m 0755 "$SCRIPT_SRC/ha-status.sh" /usr/local/sbin/ha-status.sh
install -m 0755 "$SCRIPT_SRC/bootstrap-ddb-lease-table.sh" /usr/local/sbin/bootstrap-ddb-lease-table.sh
install -m 0755 "$SCRIPT_SRC/render-strongswan-ha-conf.sh" /usr/local/sbin/render-strongswan-ha-conf.sh

install -m 0644 "$UNIT_SRC" /etc/systemd/system/muxingplus-ha.service

mkdir -p /etc/muxingplus-ha/examples
cp "$CONNTRACKD_EXAMPLE" /etc/muxingplus-ha/examples/conntrackd.conf.ftfw.example
cp "$STRONGSWAN_HA_EXAMPLE" /etc/muxingplus-ha/examples/charon-ha.conf.example
cp "$STRONGSWAN_HA_ENV_EXAMPLE" /etc/muxingplus-ha/examples/ha-sync.env.example

# Windows-created archives can preserve CRLF; normalize installed runtime files to LF.
for path in \
  /usr/local/sbin/ha-common.sh \
  /usr/local/sbin/ha-role.sh \
  /usr/local/sbin/ha-promote.sh \
  /usr/local/sbin/ha-demote.sh \
  /usr/local/sbin/ha-conntrack-promote.sh \
  /usr/local/sbin/ha-conntrack-demote.sh \
  /usr/local/sbin/ha-leader-loop.sh \
  /usr/local/sbin/ha-status.sh \
  /usr/local/sbin/bootstrap-ddb-lease-table.sh \
  /usr/local/sbin/render-strongswan-ha-conf.sh \
  /etc/systemd/system/muxingplus-ha.service \
  /etc/muxingplus-ha/examples/conntrackd.conf.ftfw.example \
  /etc/muxingplus-ha/examples/charon-ha.conf.example \
  /etc/muxingplus-ha/examples/ha-sync.env.example
do
  sed -i 's/\r$//' "$path"
done

systemctl daemon-reload

echo "Installed. Edit /etc/muxingplus-ha/ha.env then run:"
echo "  systemctl enable --now muxingplus-ha.service"
