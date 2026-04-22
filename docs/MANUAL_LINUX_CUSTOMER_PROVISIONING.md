# Manual Linux Customer Provisioning

This runbook shows how to provision one non-NAT customer and one NAT-T customer by hand with Linux commands only.

It intentionally does not use:

- `scripts/customers/deploy_customer.py`
- `scripts/customers/remove_customer.py`
- DynamoDB customer SoT writes
- DynamoDB allocation table writes
- NAT-T listener promotion

Use this only for lab work, break-glass validation, or to understand what the automated path does. If you apply this on live nodes, the SoT will not know about the customer and automated remove/reprovision flows will not own the cleanup.

Because this bypasses the allocation table, you must manually choose unused values for:

- `customer_id`
- `fwmark`
- `route_table`
- `rpdb_priority`
- `tunnel_key`
- GRE interface name
- overlay `/30`
- backend headend

The examples use already-known slots. Do not copy them for a second customer unless the first customer is removed.

The examples below use the current RPDB empty-live layout:

- Muxer public/primary private: `172.31.33.150`
- Muxer transport ENI: `172.31.69.214`
- Muxer WAN device: `ens34`
- NAT active headend underlay: `172.31.40.222`
- Non-NAT active headend underlay: `172.31.40.223`
- Headend public IKE ID: `23.20.31.151`
- Clear-side headend device: `ens36`

Replace the values before using this in another environment.

For HA, apply the muxer commands once. Apply the headend commands on the active node for traffic testing. If you stage the standby manually, use the standby underlay IP and do not activate routes that depend on an active-only clear-side gateway until that node is promoted.

## 1. Non-NAT Customer

Example customer: `legacy-cust0003`

Expected dataplane:

- Customer peer public IP: `166.213.153.41`
- Muxer forwards UDP/500 and ESP/50 to the non-NAT headend.
- Non-NAT headend terminates strongSwan.
- No outside NAT is installed.
- GRE between muxer and non-NAT headend uses key `2000`.

### 1.1 Muxer Commands

Run on the muxer:

```bash
sudo -i
set -euo pipefail

export CUST="legacy-cust0003"
export PEER_PUBLIC="166.213.153.41"
export MUXER_WAN_DEV="ens34"
export MUXER_UNDERLAY="172.31.69.214"
export MUXER_PUBLIC_SNAT="172.31.33.150"
export HEADEND_UNDERLAY="172.31.40.223"
export HEADEND_PUBLIC_ID="23.20.31.151"
export GRE_IF="gre-cust-2000"
export GRE_KEY="2000"
export OVERLAY_MUX_CIDR="169.254.0.1/30"
export TABLE_ID="2000"
export FWMARK="0x2000"
export RULE_PREF="1000"
export MX_TABLE="rpdb_mx_legacy_cust0003"

sysctl -w net.ipv4.ip_forward=1

ip link del "${GRE_IF}" 2>/dev/null || true
ip link add "${GRE_IF}" type gre local "${MUXER_UNDERLAY}" remote "${HEADEND_UNDERLAY}" ttl 64 key "${GRE_KEY}"
ip addr replace "${OVERLAY_MUX_CIDR}" dev "${GRE_IF}"
ip link set "${GRE_IF}" up

ip rule del pref "${RULE_PREF}" 2>/dev/null || true
ip rule add pref "${RULE_PREF}" fwmark "${FWMARK}" lookup "${TABLE_ID}"
ip route flush table "${TABLE_ID}" 2>/dev/null || true
ip route replace table "${TABLE_ID}" default dev "${GRE_IF}" scope link
```

Add the peer to the existing muxer passthrough table:

```bash
sudo nft list table inet muxer_passthrough >/dev/null

nft add element inet muxer_passthrough udp500_accept_peers "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft add element inet muxer_passthrough esp_accept_peers "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft add element inet muxer_passthrough udp500_dnat "{ ${PEER_PUBLIC} : ${HEADEND_UNDERLAY} }" 2>/dev/null || true
nft add element inet muxer_passthrough esp_dnat "{ ${PEER_PUBLIC} : ${HEADEND_UNDERLAY} }" 2>/dev/null || true
nft add element inet muxer_passthrough udp500_snat "{ ${HEADEND_UNDERLAY} . ${PEER_PUBLIC} : ${MUXER_PUBLIC_SNAT} }" 2>/dev/null || true
nft add element inet muxer_passthrough esp_snat "{ ${HEADEND_UNDERLAY} . ${PEER_PUBLIC} : ${MUXER_PUBLIC_SNAT} }" 2>/dev/null || true
nft add element inet muxer_passthrough natd_in_pairs "{ ${PEER_PUBLIC} . ${MUXER_PUBLIC_SNAT}, ${PEER_PUBLIC} . ${HEADEND_UNDERLAY} }" 2>/dev/null || true
nft add element inet muxer_passthrough natd_out_pairs "{ ${HEADEND_UNDERLAY} . ${PEER_PUBLIC} }" 2>/dev/null || true
```

Create the per-customer muxer SNAT table:

```bash
nft delete table ip "${MX_TABLE}" 2>/dev/null || true
nft -f - <<EOF
add table ip ${MX_TABLE}
add chain ip ${MX_TABLE} postrouting { type nat hook postrouting priority srcnat; policy accept; }
add rule ip ${MX_TABLE} postrouting oifname "${MUXER_WAN_DEV}" ip saddr ${HEADEND_UNDERLAY} ip daddr ${PEER_PUBLIC} udp sport 500 snat to ${MUXER_PUBLIC_SNAT}
add rule ip ${MX_TABLE} postrouting oifname "${MUXER_WAN_DEV}" ip saddr ${HEADEND_UNDERLAY} ip daddr ${PEER_PUBLIC} ip protocol esp snat to ${MUXER_PUBLIC_SNAT}
add rule ip ${MX_TABLE} postrouting oifname "${MUXER_WAN_DEV}" ip saddr ${HEADEND_PUBLIC_ID} ip daddr ${PEER_PUBLIC} udp sport 500 snat to ${MUXER_PUBLIC_SNAT}
add rule ip ${MX_TABLE} postrouting oifname "${MUXER_WAN_DEV}" ip saddr ${HEADEND_PUBLIC_ID} ip daddr ${PEER_PUBLIC} ip protocol esp snat to ${MUXER_PUBLIC_SNAT}
EOF
```

Verify muxer state:

```bash
ip -d link show "${GRE_IF}"
ip addr show dev "${GRE_IF}"
ip rule show | grep "${FWMARK}"
ip route show table "${TABLE_ID}"
ip route get "${PEER_PUBLIC}" mark "${FWMARK}"
nft list table ip "${MX_TABLE}"
nft list table inet muxer_passthrough | egrep "${PEER_PUBLIC}|${HEADEND_UNDERLAY}"
```

### 1.2 Non-NAT Headend Commands

Run on the non-NAT active headend:

```bash
sudo -i
set -euo pipefail

export CUST="legacy-cust0003"
export PSK="REPLACE_WITH_CUSTOMER_PSK"
export PEER_PUBLIC="166.213.153.41"
export LOCAL_ADDR="172.31.40.223"
export LOCAL_ID="23.20.31.151"
export REMOTE_ID="166.213.153.41"
export MUXER_UNDERLAY="172.31.69.214"
export GRE_IF="gre-cust-2000"
export GRE_KEY="2000"
export OVERLAY_HEADEND_CIDR="169.254.0.2/30"
export OVERLAY_MUX_IP="169.254.0.1"
export CLEAR_DEV="ens36"

sysctl -w net.ipv4.ip_forward=1

ip link del "${GRE_IF}" 2>/dev/null || true
ip link add "${GRE_IF}" type gre local "${LOCAL_ADDR}" remote "${MUXER_UNDERLAY}" ttl 64 key "${GRE_KEY}"
ip addr replace "${OVERLAY_HEADEND_CIDR}" dev "${GRE_IF}"
ip link set "${GRE_IF}" up

ip route replace "${PEER_PUBLIC}/32" via "${OVERLAY_MUX_IP}" dev "${GRE_IF}"
ip route replace 172.31.54.39/32 dev "${CLEAR_DEV}"
ip route replace 194.138.36.80/28 dev "${CLEAR_DEV}"
ip route replace 172.30.0.90/32 dev "${CLEAR_DEV}"
```

Install the strongSwan config:

```bash
install -d -m 0755 /etc/swanctl/conf.d
cat >/etc/swanctl/conf.d/${CUST}.conf <<EOF
connections {
  ${CUST} {
    version = 2
    local_addrs = ${LOCAL_ADDR}
    remote_addrs = ${PEER_PUBLIC}
    proposals = aes256-sha256-modp2048,aes256-sha256-modp4096
    mobike = no
    fragmentation = yes
    dpd_delay = 10s
    dpd_timeout = 120s
    local {
      auth = psk
      id = ${LOCAL_ID}
    }
    remote {
      auth = psk
      id = ${REMOTE_ID}
    }
    children {
      ${CUST}-child {
        local_ts = 172.31.54.39/32,194.138.36.80/28,172.30.0.90/32
        remote_ts = 10.129.4.12/32,192.168.1.59/32
        mode = tunnel
        start_action = start
        esp_proposals = aes256-sha256-modp2048,aes256-sha256-modp4096
        dpd_action = restart
        replay_window = 32
        copy_df = no
      }
    }
  }
}

secrets {
  ${CUST}-psk {
    id-1 = ${LOCAL_ID}
    id-2 = ${REMOTE_ID}
    secret = "${PSK}"
  }
}
EOF
chmod 600 /etc/swanctl/conf.d/${CUST}.conf

swanctl --load-all
swanctl --initiate --ike "${CUST}" || true
```

Verify non-NAT headend state:

```bash
ip -d link show "${GRE_IF}"
ip route get "${PEER_PUBLIC}"
swanctl --list-conns | egrep -A12 "${CUST}|${PEER_PUBLIC}|10.129.4.12|192.168.1.59"
swanctl --list-sas | egrep -A12 "${CUST}|bytes|packets"
tcpdump -nni any "host ${PEER_PUBLIC} and (udp port 500 or esp)"
```

## 2. NAT-T Customer

Example customer: `vpn-customer-stage1-15-cust-0004`

Expected dataplane:

- Customer peer public IP: `3.237.201.84`
- Muxer forwards UDP/500 and UDP/4500 to the NAT headend.
- NAT headend terminates strongSwan with NAT-T encapsulation.
- Outside NAT maps customer target `10.128.4.2` to real far-end `194.138.36.86`.
- GRE between muxer and NAT headend uses key `41000`.

Do not install the `route_via 172.31.63.44 dev ens36` route on the non-NAT headend. That outside-NAT route belongs only on the NAT headend.

### 2.1 Muxer Commands

Run on the muxer:

```bash
sudo -i
set -euo pipefail

export CUST="vpn-customer-stage1-15-cust-0004"
export PEER_PUBLIC="3.237.201.84"
export MUXER_WAN_DEV="ens34"
export MUXER_UNDERLAY="172.31.69.214"
export MUXER_PUBLIC_SNAT="172.31.33.150"
export HEADEND_UNDERLAY="172.31.40.222"
export HEADEND_PUBLIC_ID="23.20.31.151"
export GRE_IF="gre-vpn-41000"
export GRE_KEY="41000"
export OVERLAY_MUX_CIDR="169.254.128.1/30"
export TABLE_ID="41000"
export FWMARK="0x41000"
export RULE_PREF="11000"
export MX_TABLE="rpdb_mx_vpn_customer_stage1_15_cust_0004"

sysctl -w net.ipv4.ip_forward=1

ip link del "${GRE_IF}" 2>/dev/null || true
ip link add "${GRE_IF}" type gre local "${MUXER_UNDERLAY}" remote "${HEADEND_UNDERLAY}" ttl 64 key "${GRE_KEY}"
ip addr replace "${OVERLAY_MUX_CIDR}" dev "${GRE_IF}"
ip link set "${GRE_IF}" up

ip rule del pref "${RULE_PREF}" 2>/dev/null || true
ip rule add pref "${RULE_PREF}" fwmark "${FWMARK}" lookup "${TABLE_ID}"
ip route flush table "${TABLE_ID}" 2>/dev/null || true
ip route replace table "${TABLE_ID}" default dev "${GRE_IF}" scope link
```

Add NAT-T peer entries to the existing muxer passthrough table:

```bash
sudo nft list table inet muxer_passthrough >/dev/null

nft add element inet muxer_passthrough udp500_accept_peers "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft add element inet muxer_passthrough udp4500_accept_peers "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft add element inet muxer_passthrough udp500_dnat "{ ${PEER_PUBLIC} : ${HEADEND_UNDERLAY} }" 2>/dev/null || true
nft add element inet muxer_passthrough udp4500_dnat "{ ${PEER_PUBLIC} : ${HEADEND_UNDERLAY} }" 2>/dev/null || true
nft add element inet muxer_passthrough udp500_snat "{ ${HEADEND_UNDERLAY} . ${PEER_PUBLIC} : ${MUXER_PUBLIC_SNAT} }" 2>/dev/null || true
nft add element inet muxer_passthrough udp4500_snat "{ ${HEADEND_UNDERLAY} . ${PEER_PUBLIC} : ${MUXER_PUBLIC_SNAT} }" 2>/dev/null || true
```

Create the per-customer muxer SNAT table:

```bash
nft delete table ip "${MX_TABLE}" 2>/dev/null || true
nft -f - <<EOF
add table ip ${MX_TABLE}
add chain ip ${MX_TABLE} postrouting { type nat hook postrouting priority srcnat; policy accept; }
add rule ip ${MX_TABLE} postrouting oifname "${MUXER_WAN_DEV}" ip saddr ${HEADEND_UNDERLAY} ip daddr ${PEER_PUBLIC} udp sport 500 snat to ${MUXER_PUBLIC_SNAT}
add rule ip ${MX_TABLE} postrouting oifname "${MUXER_WAN_DEV}" ip saddr ${HEADEND_UNDERLAY} ip daddr ${PEER_PUBLIC} udp sport 4500 snat to ${MUXER_PUBLIC_SNAT}
add rule ip ${MX_TABLE} postrouting oifname "${MUXER_WAN_DEV}" ip saddr ${HEADEND_PUBLIC_ID} ip daddr ${PEER_PUBLIC} udp sport 500 snat to ${MUXER_PUBLIC_SNAT}
add rule ip ${MX_TABLE} postrouting oifname "${MUXER_WAN_DEV}" ip saddr ${HEADEND_PUBLIC_ID} ip daddr ${PEER_PUBLIC} udp sport 4500 snat to ${MUXER_PUBLIC_SNAT}
EOF
```

Verify muxer state:

```bash
ip -d link show "${GRE_IF}"
ip addr show dev "${GRE_IF}"
ip rule show | grep "${FWMARK}"
ip route show table "${TABLE_ID}"
ip route get "${PEER_PUBLIC}" mark "${FWMARK}"
nft list table ip "${MX_TABLE}"
nft list table inet muxer_passthrough | egrep "${PEER_PUBLIC}|${HEADEND_UNDERLAY}"
```

### 2.2 NAT Headend Commands

Run on the NAT active headend:

```bash
sudo -i
set -euo pipefail

export CUST="vpn-customer-stage1-15-cust-0004"
export PSK="REPLACE_WITH_CUSTOMER_PSK"
export PEER_PUBLIC="3.237.201.84"
export LOCAL_ADDR="172.31.40.222"
export LOCAL_ID="23.20.31.151"
export REMOTE_ID="3.237.201.84"
export MUXER_UNDERLAY="172.31.69.214"
export GRE_IF="gre-vpn-41000"
export GRE_KEY="41000"
export OVERLAY_HEADEND_CIDR="169.254.128.2/30"
export OVERLAY_MUX_IP="169.254.128.1"
export CLEAR_DEV="ens36"
export OUTSIDE_ROUTE_GW="172.31.63.44"
export OUTSIDE_NAT_TABLE="rpdb_on_vpn_customer_stage1_15_cust_0004"

sysctl -w net.ipv4.ip_forward=1

ip link del "${GRE_IF}" 2>/dev/null || true
ip link add "${GRE_IF}" type gre local "${LOCAL_ADDR}" remote "${MUXER_UNDERLAY}" ttl 64 key "${GRE_KEY}"
ip addr replace "${OVERLAY_HEADEND_CIDR}" dev "${GRE_IF}"
ip link set "${GRE_IF}" up

ip route replace "${PEER_PUBLIC}/32" via "${OVERLAY_MUX_IP}" dev "${GRE_IF}"
ip route replace 194.138.36.80/28 via "${OUTSIDE_ROUTE_GW}" dev "${CLEAR_DEV}"
ip route replace 194.138.36.86/32 via "${OUTSIDE_ROUTE_GW}" dev "${CLEAR_DEV}"
```

Install the strongSwan NAT-T config:

```bash
install -d -m 0755 /etc/swanctl/conf.d
cat >/etc/swanctl/conf.d/${CUST}.conf <<EOF
connections {
  ${CUST} {
    version = 2
    local_addrs = ${LOCAL_ADDR}
    remote_addrs = ${PEER_PUBLIC}
    proposals = aes256-sha256-modp2048,aes256-sha256-modp4096
    encap = yes
    mobike = no
    fragmentation = yes
    dpd_delay = 10s
    dpd_timeout = 120s
    local {
      auth = psk
      id = ${LOCAL_ID}
    }
    remote {
      auth = psk
      id = ${REMOTE_ID}
    }
    children {
      ${CUST}-child {
        local_ts = 172.31.54.39/32,194.138.36.80/28,10.128.4.2/32
        remote_ts = 10.129.3.0/24
        mode = tunnel
        start_action = start
        esp_proposals = aes256-sha256-modp2048,aes256-sha256-modp4096
        dpd_action = restart
        replay_window = 32
        copy_df = no
      }
    }
  }
}

secrets {
  ${CUST}-psk {
    id-1 = ${LOCAL_ID}
    id-2 = ${REMOTE_ID}
    secret = "${PSK}"
  }
}
EOF
chmod 600 /etc/swanctl/conf.d/${CUST}.conf

swanctl --load-all
swanctl --initiate --ike "${CUST}" || true
```

Install the outside NAT table:

```bash
nft delete table ip "${OUTSIDE_NAT_TABLE}" 2>/dev/null || true
nft -f - <<EOF
add table ip ${OUTSIDE_NAT_TABLE}
add set ip ${OUTSIDE_NAT_TABLE} cust_vpn_customer_stage1_15_cust_0004_outside_customer_sources_v4 { type ipv4_addr; flags interval; }
add element ip ${OUTSIDE_NAT_TABLE} cust_vpn_customer_stage1_15_cust_0004_outside_customer_sources_v4 { 10.129.3.154 }
add set ip ${OUTSIDE_NAT_TABLE} cust_vpn_customer_stage1_15_cust_0004_outside_translated_v4 { type ipv4_addr; }
add element ip ${OUTSIDE_NAT_TABLE} cust_vpn_customer_stage1_15_cust_0004_outside_translated_v4 { 10.128.4.2 }
add set ip ${OUTSIDE_NAT_TABLE} cust_vpn_customer_stage1_15_cust_0004_outside_real_v4 { type ipv4_addr; }
add element ip ${OUTSIDE_NAT_TABLE} cust_vpn_customer_stage1_15_cust_0004_outside_real_v4 { 194.138.36.86 }
add map ip ${OUTSIDE_NAT_TABLE} cust_vpn_customer_stage1_15_cust_0004_outside_dnat_v4 { type ipv4_addr : ipv4_addr; }
add element ip ${OUTSIDE_NAT_TABLE} cust_vpn_customer_stage1_15_cust_0004_outside_dnat_v4 { 10.128.4.2 : 194.138.36.86 }
add map ip ${OUTSIDE_NAT_TABLE} cust_vpn_customer_stage1_15_cust_0004_outside_snat_v4 { type ipv4_addr : ipv4_addr; }
add element ip ${OUTSIDE_NAT_TABLE} cust_vpn_customer_stage1_15_cust_0004_outside_snat_v4 { 194.138.36.86 : 10.128.4.2 }
add chain ip ${OUTSIDE_NAT_TABLE} prerouting { type nat hook prerouting priority dstnat; policy accept; }
add chain ip ${OUTSIDE_NAT_TABLE} postrouting { type nat hook postrouting priority srcnat; policy accept; }
add rule ip ${OUTSIDE_NAT_TABLE} prerouting ip saddr @cust_vpn_customer_stage1_15_cust_0004_outside_customer_sources_v4 ip daddr @cust_vpn_customer_stage1_15_cust_0004_outside_translated_v4 dnat to ip daddr map @cust_vpn_customer_stage1_15_cust_0004_outside_dnat_v4
add rule ip ${OUTSIDE_NAT_TABLE} postrouting ip saddr @cust_vpn_customer_stage1_15_cust_0004_outside_real_v4 ip daddr @cust_vpn_customer_stage1_15_cust_0004_outside_customer_sources_v4 snat to ip saddr map @cust_vpn_customer_stage1_15_cust_0004_outside_snat_v4
EOF
```

Verify NAT headend state:

```bash
ip -d link show "${GRE_IF}"
ip route get "${PEER_PUBLIC}"
ip route get 194.138.36.86
nft list table ip "${OUTSIDE_NAT_TABLE}"
swanctl --list-conns | egrep -A12 "${CUST}|${PEER_PUBLIC}|10.129.3|10.128.4.2|194.138.36"
swanctl --list-sas | egrep -A12 "${CUST}|bytes|packets"
tcpdump -nni any "host ${PEER_PUBLIC} and udp port 4500"
tcpdump -nni any "host 10.129.3.154 or host 10.128.4.2 or host 194.138.36.86"
```

Expected customer-side tests:

```bash
ping -c 4 -W 1 -I 10.129.3.154 10.128.4.2
ping -c 4 -W 1 -I 10.129.3.154 194.138.36.86
```

## 3. Manual Cleanup

These commands remove only the Linux runtime state. They do not touch SoT because this runbook does not create SoT.

### 3.1 Non-NAT Cleanup

On the non-NAT headend:

```bash
sudo -i
export CUST="legacy-cust0003"
export PEER_PUBLIC="166.213.153.41"
export GRE_IF="gre-cust-2000"

swanctl --terminate --ike "${CUST}" 2>/dev/null || true
rm -f "/etc/swanctl/conf.d/${CUST}.conf"
swanctl --load-all || true

ip route del "${PEER_PUBLIC}/32" 2>/dev/null || true
ip link del "${GRE_IF}" 2>/dev/null || true
```

On the muxer:

```bash
sudo -i
export CUST="legacy-cust0003"
export PEER_PUBLIC="166.213.153.41"
export HEADEND_UNDERLAY="172.31.40.223"
export GRE_IF="gre-cust-2000"
export TABLE_ID="2000"
export RULE_PREF="1000"
export MX_TABLE="rpdb_mx_legacy_cust0003"

nft delete table ip "${MX_TABLE}" 2>/dev/null || true
nft delete element inet muxer_passthrough udp500_accept_peers "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft delete element inet muxer_passthrough esp_accept_peers "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft delete element inet muxer_passthrough udp500_dnat "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft delete element inet muxer_passthrough esp_dnat "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft delete element inet muxer_passthrough udp500_snat "{ ${HEADEND_UNDERLAY} . ${PEER_PUBLIC} }" 2>/dev/null || true
nft delete element inet muxer_passthrough esp_snat "{ ${HEADEND_UNDERLAY} . ${PEER_PUBLIC} }" 2>/dev/null || true
nft delete element inet muxer_passthrough natd_out_pairs "{ ${HEADEND_UNDERLAY} . ${PEER_PUBLIC} }" 2>/dev/null || true

ip rule del pref "${RULE_PREF}" 2>/dev/null || true
ip route flush table "${TABLE_ID}" 2>/dev/null || true
ip link del "${GRE_IF}" 2>/dev/null || true
```

### 3.2 NAT-T Cleanup

On the NAT headend:

```bash
sudo -i
export CUST="vpn-customer-stage1-15-cust-0004"
export PEER_PUBLIC="3.237.201.84"
export GRE_IF="gre-vpn-41000"
export OUTSIDE_NAT_TABLE="rpdb_on_vpn_customer_stage1_15_cust_0004"

swanctl --terminate --ike "${CUST}" 2>/dev/null || true
rm -f "/etc/swanctl/conf.d/${CUST}.conf"
swanctl --load-all || true

nft delete table ip "${OUTSIDE_NAT_TABLE}" 2>/dev/null || true
ip route del "${PEER_PUBLIC}/32" 2>/dev/null || true
ip route del 194.138.36.86/32 2>/dev/null || true
ip route del 194.138.36.80/28 2>/dev/null || true
ip link del "${GRE_IF}" 2>/dev/null || true
```

On the muxer:

```bash
sudo -i
export CUST="vpn-customer-stage1-15-cust-0004"
export PEER_PUBLIC="3.237.201.84"
export HEADEND_UNDERLAY="172.31.40.222"
export GRE_IF="gre-vpn-41000"
export TABLE_ID="41000"
export RULE_PREF="11000"
export MX_TABLE="rpdb_mx_vpn_customer_stage1_15_cust_0004"

nft delete table ip "${MX_TABLE}" 2>/dev/null || true
nft delete element inet muxer_passthrough udp500_accept_peers "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft delete element inet muxer_passthrough udp4500_accept_peers "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft delete element inet muxer_passthrough udp500_dnat "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft delete element inet muxer_passthrough udp4500_dnat "{ ${PEER_PUBLIC} }" 2>/dev/null || true
nft delete element inet muxer_passthrough udp500_snat "{ ${HEADEND_UNDERLAY} . ${PEER_PUBLIC} }" 2>/dev/null || true
nft delete element inet muxer_passthrough udp4500_snat "{ ${HEADEND_UNDERLAY} . ${PEER_PUBLIC} }" 2>/dev/null || true

ip rule del pref "${RULE_PREF}" 2>/dev/null || true
ip route flush table "${TABLE_ID}" 2>/dev/null || true
ip link del "${GRE_IF}" 2>/dev/null || true
```
