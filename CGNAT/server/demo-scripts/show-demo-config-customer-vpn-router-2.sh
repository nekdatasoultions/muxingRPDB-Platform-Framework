#!/usr/bin/env bash
set -euo pipefail

section() {
  printf '\n===== %s =====\n' "$1"
}

show_file() {
  local path="$1"
  section "FILE ${path}"
  sudo test -f "$path" && sudo sed -n '1,240p' "$path" || echo "missing: $path"
}

show_redacted() {
  local path="$1"
  section "FILE ${path} (REDACTED)"
  if sudo test -f "$path"; then
    sudo sed -E 's/(secret = ).+/\1"<redacted>"/' "$path"
  else
    echo "missing: $path"
  fi
}

show_cmd() {
  local title="$1"
  shift
  section "$title"
  "$@"
}

show_service() {
  sudo bash -lc '
    systemctl --no-pager --full status strongswan-starter 2>/dev/null ||
    systemctl --no-pager --full status strongswan 2>/dev/null ||
    systemctl --no-pager --full status charon-systemd 2>/dev/null ||
    systemctl --no-pager --full list-units --type=service | egrep "strongswan|charon" ||
    true
  '
}

show_cmd "HOSTNAME" hostname
show_cmd "STRONGSWAN SERVICE" show_service
show_file /etc/strongswan.d/cgnat-scenario1-rpdb-empty-live-customer_vpn_router_2.conf
show_file /etc/swanctl/conf.d/cgnat-scenario1-rpdb-empty-live-customer_vpn_router_2-outer.conf
show_file /etc/swanctl/conf.d/cgnat-scenario1-rpdb-empty-live-customer_vpn_router_2-inner.conf
show_redacted /etc/swanctl/conf.d/cgnat-scenario1-rpdb-empty-live-customer_vpn_router_2-inner-secrets.conf
show_cmd "CERT FILES" sudo ls -l /etc/swanctl/x509 /etc/swanctl/private /etc/swanctl/x509ca
show_cmd "LOADED CERTS" sudo swanctl --list-certs
show_cmd "CONFIGURED CONNECTIONS" sudo swanctl --list-conns
show_cmd "ACTIVE SAS" sudo swanctl --list-sas
show_cmd "LOOPBACK" ip addr show lo
show_cmd "INTERFACES" ip -brief addr
show_cmd "XFRM LINK" ip -d link show cgxfrm-r2
show_cmd "ROUTES" ip route show
