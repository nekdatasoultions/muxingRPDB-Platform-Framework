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

show_log_grep() {
  local title="$1"
  local pattern="$2"
  section "$title"
  if ! sudo journalctl --no-pager -o short-iso \
    -u strongswan-starter \
    -u strongswan \
    -u charon-systemd 2>/dev/null |
    egrep -i "$pattern" |
    tail -n 80; then
    echo "No matching log lines found."
  fi
}

show_nat_excerpt() {
  local pattern="$1"
  if command -v nft >/dev/null 2>&1; then
    sudo bash -lc "nft list ruleset 2>/dev/null | grep -E -B 8 -A 8 '$pattern' || true"
  elif command -v iptables-save >/dev/null 2>&1; then
    sudo bash -lc "iptables-save -t nat | egrep '$pattern|\\*nat|COMMIT' || true"
    echo
    sudo bash -lc "iptables -t nat -L -n -v | egrep '$pattern|Chain' || true"
  elif command -v iptables >/dev/null 2>&1; then
    sudo bash -lc "iptables -t nat -S | egrep '$pattern' || true"
    echo
    sudo bash -lc "iptables -t nat -L -n -v | egrep '$pattern|Chain' || true"
  else
    echo "Neither nft nor iptables found"
  fi
}

show_nat_table() {
  local table_name="$1"
  local fallback_pattern="$2"
  if command -v nft >/dev/null 2>&1; then
    if ! sudo nft list table ip "$table_name" 2>/dev/null; then
      echo "nft table $table_name not present, falling back to filtered excerpt"
      show_nat_excerpt "$fallback_pattern"
    fi
  else
    show_nat_excerpt "$fallback_pattern"
  fi
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
show_log_grep \
  "INNER SECRET NEGOTIATION LOGS" \
  'cgnat-s1-be-r(1|2)|cgnat-scenario1-rpdb-empty-live-customer_vpn_router_(1|2)-inner|pre-shared|shared key|psk'
section "CUSTOMER 1 NAT SUMMARY"
echo "Inside NAT: 10.20.30.10 -> 10.20.20.10"
echo "Outside NAT: 194.138.36.86 <-> 10.20.40.10 (customer source 10.20.30.10)"
show_cmd \
  "CUSTOMER 1 INSIDE NAT TABLE" \
  show_nat_table \
  'rpdb_hn_example_cgnat_customer_1_local_pki' \
  '10\.20\.30\.10|10\.20\.20\.10|23\.20\.31\.151|194\.138\.36\.86|rpdb_hn_example_cgnat_customer_1_local_pki'
show_cmd \
  "CUSTOMER 1 OUTSIDE NAT TABLE" \
  show_nat_table \
  'rpdb_on_example_cgnat_customer_1_local_pki' \
  '10\.20\.30\.10|10\.20\.40\.10|194\.138\.36\.86|rpdb_on_example_cgnat_customer_1_local_pki'
show_cmd "LOOPBACK" ip addr show lo
show_cmd "INTERFACES" ip -brief addr
show_cmd "KEY ROUTES" sh -c "ip route show | egrep '194\\.138\\.36\\.86|10\\.250\\.1\\.(10|11)|172\\.31\\.48\\.(20|21)' || true"
