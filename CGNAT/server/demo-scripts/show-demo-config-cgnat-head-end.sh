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
show_file /etc/strongswan.d/cgnat-scenario1-rpdb-empty-live.conf
show_file /etc/swanctl/conf.d/cgnat-scenario1-rpdb-empty-live-outer.conf
show_cmd "CERT FILES" sudo ls -l /etc/swanctl/x509 /etc/swanctl/private /etc/swanctl/x509ca
show_cmd "LOADED CERTS" sudo swanctl --list-certs
show_cmd "CONFIGURED CONNECTIONS" sudo swanctl --list-conns
show_cmd "ACTIVE SAS" sudo swanctl --list-sas
show_cmd "INTERFACES" ip -brief addr
show_cmd "XFRM LINKS" sh -c "ip -d link show dev cgxfrm-r1; echo; ip -d link show dev cgxfrm-r2"
show_cmd "GRE LINK" ip -d link show cgnat-s1-gre1
show_cmd "ROUTES" ip route show
