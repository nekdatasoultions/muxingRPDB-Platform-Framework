#!/usr/bin/env bash
set -euo pipefail

if command -v dnf >/dev/null 2>&1; then
  PKG_MGR="dnf"
elif command -v yum >/dev/null 2>&1; then
  PKG_MGR="yum"
else
  echo "No supported package manager found (dnf/yum)"
  exit 1
fi

"$PKG_MGR" install -y \
  iproute \
  iptables-nft \
  iptables-services \
  nftables \
  conntrack-tools \
  tcpdump \
  jq \
  python3 \
  python3-pip \
  python3-devel \
  gcc \
  libnetfilter_queue-devel

if "$PKG_MGR" list available strongswan >/dev/null 2>&1; then
  "$PKG_MGR" install -y strongswan
else
  echo "strongswan package not found in current repos; skipping."
fi

pip3 install --upgrade pyyaml scapy NetfilterQueue
