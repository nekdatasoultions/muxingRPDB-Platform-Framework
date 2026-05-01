#!/usr/bin/env bash
set -euo pipefail

section() {
  printf '\n===== %s =====\n' "$1"
}

show_file() {
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
show_file /etc/swanctl/conf.d/rpdb-customers/cgnat-s1-be-r1.conf
show_file /etc/swanctl/conf.d/rpdb-customers/cgnat-s1-be-r2.conf
show_cmd "CONFIGURED CONNECTIONS" sudo swanctl --list-conns
show_cmd "ACTIVE SAS" sudo swanctl --list-sas
show_cmd "LOOPBACK" ip addr show lo
show_cmd "INTERFACES" ip -brief addr
show_cmd "KEY ROUTES" sh -c "ip route show | egrep '194\\.138\\.36\\.86|10\\.250\\.1\\.(10|11)|172\\.31\\.48\\.(20|21)' || true"
