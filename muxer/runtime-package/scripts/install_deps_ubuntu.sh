#!/usr/bin/env bash
set -euo pipefail
apt-get update
apt-get install -y \
  iproute2 \
  iptables \
  conntrack \
  tcpdump \
  jq \
  python3 \
  python3-pip \
  python3-dev \
  build-essential \
  libnetfilter-queue-dev \
  libnfnetlink-dev \
  strongswan
pip3 install --upgrade pyyaml scapy NetfilterQueue
