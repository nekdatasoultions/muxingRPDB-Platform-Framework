#!/usr/bin/env bash
set -euo pipefail

section() {
  printf '\n===== %s =====\n' "$1"
}

show_cmd() {
  local title="$1"
  shift
  section "$title"
  "$@"
}

show_nat_rules() {
  if command -v iptables >/dev/null 2>&1; then
    sudo iptables -t nat -S
  elif command -v nft >/dev/null 2>&1; then
    sudo bash -lc '
      nft list table ip cgnat_scenario1_nat 2>/dev/null ||
      nft list ruleset | sed -n "/type nat hook postrouting/,/}/p" ||
      true
    '
  else
    echo "Neither iptables nor nft found"
  fi
}

show_forward_rules() {
  if command -v iptables >/dev/null 2>&1; then
    sudo iptables -S FORWARD
  elif command -v nft >/dev/null 2>&1; then
    sudo bash -lc 'nft list ruleset | sed -n "/hook forward/,/}/p" || true'
  else
    echo "Neither iptables nor nft found"
  fi
}

section "ROLE"
echo "Transit/NAT only node. No outer or inner IPsec tunnel should terminate here."
show_cmd "HOSTNAME" hostname
show_cmd "INTERFACES" ip -brief addr
show_cmd "ROUTES" ip route show
show_cmd "IP FORWARD" sysctl net.ipv4.ip_forward
show_cmd "NAT RULES" show_nat_rules
show_cmd "FORWARD RULES" show_forward_rules
section "STRONGSWAN FILES"
if sudo test -d /etc/swanctl/conf.d; then
  sudo find /etc/swanctl/conf.d -maxdepth 2 -type f | sort
else
  echo "No /etc/swanctl/conf.d present"
fi
