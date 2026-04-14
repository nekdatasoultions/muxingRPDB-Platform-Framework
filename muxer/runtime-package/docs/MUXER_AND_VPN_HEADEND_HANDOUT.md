# Muxer and VPN Head-End Handout

## Purpose

This handout explains how the muxer and the VPN head end are configured, what each layer is responsible for, and how packets are handled end to end.

The concrete example used throughout is NAT-T customer `vpn-customer-stage1-15-cust-0003`.

Key example values:

- Customer peer IP: `3.215.115.178`
- Shared public VPN IP: `54.204.221.89`
- Muxer private/inside IP: `172.31.42.35`
- NAT head-end underlay IP: `172.31.40.221`
- Muxer GRE interface: `gre-s15-0003`
- Overlay link:
  - Muxer side: `169.254.103.1/30`
  - Head-end side: `169.254.103.2/30`
- Customer fwmark: `0x41003`
- Customer route table: `41003`
- Customer-side overlapping source being tested: `10.129.3.154/32`
- Demo/core host: `172.31.54.39/32`
- Customer translated internal block on the head end: `172.30.0.64/27`

Note:
- In the muxer examples below, `<pub_if>` means the public NIC on the muxer.
- In rendered examples this is often `ens5`, but the live node can use a different interface name.

## High-Level Split of Responsibilities

### Muxer

The muxer does not terminate IPsec. Its job is to:

1. Receive encrypted traffic on the shared public VPN IP.
2. Identify which customer sent the traffic.
3. Mark the packet with that customer's fwmark.
4. Route the packet into the customer's dedicated GRE tunnel.
5. Deliver the encrypted traffic to the correct head-end cluster.

### VPN Head End

The VPN head end does the actual IPsec termination. Its job is to:

1. Terminate IKE/IPsec for the customer.
2. Apply overlap-preserving post-IPsec NAT when required.
3. Mark and route reply traffic back into the correct customer tunnel.
4. Re-encrypt and return traffic through the muxer path.

## Muxer Configuration

### 1. Prebuilt Customer GRE Transport

The muxer builds one transport per customer.

Example statements:

```bash
ip tunnel add gre-s15-0003 mode gre local 172.31.42.35 remote 172.31.40.221 ttl 64 key 41003
ip addr replace 169.254.103.1/30 dev gre-s15-0003
ip link set gre-s15-0003 up
ip rule add fwmark 0x41003 lookup 41003
ip route replace default dev gre-s15-0003 table 41003
```

What each statement means:

- `ip tunnel add ...`
  Creates the dedicated GRE path from the muxer to the NAT head end for this customer.
- `ip addr replace ...`
  Places the muxer-side overlay address on that GRE.
- `ip link set ... up`
  Brings the transport up.
- `ip rule add fwmark ...`
  Tells Linux that packets marked `0x41003` must use route table `41003`.
- `ip route replace default dev gre-s15-0003 table 41003`
  Sends all traffic in that table into this customer's GRE tunnel.

### 2. Muxer Packet Classification and Steering

The muxer creates iptables rules in these chains:

- `MUXER_FILTER`
- `MUXER_MANGLE`
- `MUXER_NAT_PRE`
- `MUXER_NAT_POST`

These are generated from the muxer dataplane logic.

### UDP/500

```bash
iptables -A MUXER_FILTER -i <pub_if> -s 3.215.115.178/32 -d 54.204.221.89 -p udp --dport 500 -j ACCEPT
iptables -t mangle -A MUXER_MANGLE -i <pub_if> -s 3.215.115.178/32 -d 54.204.221.89 -p udp --dport 500 -j MARK --set-mark 0x41003
iptables -t mangle -A MUXER_MANGLE -i <pub_if> -s 3.215.115.178/32 -d 172.31.42.35 -p udp --dport 500 -j MARK --set-mark 0x41003
iptables -t nat -A MUXER_NAT_PRE -i <pub_if> -s 3.215.115.178/32 -d 172.31.42.35 -p udp --dport 500 -j DNAT --to-destination 172.31.40.221
iptables -t nat -A MUXER_NAT_POST -o <pub_if> -s 172.31.40.221 -d 3.215.115.178/32 -p udp --sport 500 -j SNAT --to-source 172.31.42.35
```

Meaning:

- `MUXER_FILTER`
  Allows known customer IKE traffic.
- `MUXER_MANGLE`
  Applies the customer fwmark so Linux chooses the right route table.
- second `MUXER_MANGLE` rule
  Matches traffic arriving for the private ENI address behind the EIP.
- `MUXER_NAT_PRE`
  Rewrites the encrypted packet so it is delivered to the correct backend head end.
- `MUXER_NAT_POST`
  Rewrites backend replies so they leave as the muxer edge identity.

### UDP/4500

```bash
iptables -A MUXER_FILTER -i <pub_if> -s 3.215.115.178/32 -d 54.204.221.89 -p udp --dport 4500 -j ACCEPT
iptables -t mangle -A MUXER_MANGLE -i <pub_if> -s 3.215.115.178/32 -d 54.204.221.89 -p udp --dport 4500 -j MARK --set-mark 0x41003
iptables -t mangle -A MUXER_MANGLE -i <pub_if> -s 3.215.115.178/32 -d 172.31.42.35 -p udp --dport 4500 -j MARK --set-mark 0x41003
iptables -t nat -A MUXER_NAT_PRE -i <pub_if> -s 3.215.115.178/32 -d 172.31.42.35 -p udp --dport 4500 -j DNAT --to-destination 172.31.40.221
iptables -t nat -A MUXER_NAT_POST -o <pub_if> -s 172.31.40.221 -d 3.215.115.178/32 -p udp --sport 4500 -j SNAT --to-source 172.31.42.35
```

Meaning:

- This is the active NAT-T path.
- The muxer accepts, marks, DNATs, and routes customer `0003` NAT-T traffic into `gre-s15-0003`.

### ESP/50

```bash
iptables -A MUXER_FILTER -i <pub_if> -s 3.215.115.178/32 -d 54.204.221.89 -p 50 -j ACCEPT
iptables -t mangle -A MUXER_MANGLE -i <pub_if> -s 3.215.115.178/32 -d 54.204.221.89 -p 50 -j MARK --set-mark 0x41003
iptables -t mangle -A MUXER_MANGLE -i <pub_if> -s 3.215.115.178/32 -d 172.31.42.35 -p 50 -j MARK --set-mark 0x41003
iptables -t nat -A MUXER_NAT_PRE -i <pub_if> -s 3.215.115.178/32 -d 172.31.42.35 -p 50 -j DNAT --to-destination 172.31.40.221
iptables -t nat -A MUXER_NAT_POST -o <pub_if> -s 172.31.40.221 -d 3.215.115.178/32 -p 50 -j SNAT --to-source 172.31.42.35
```

Meaning:

- This supports peers that still use native ESP in addition to UDP-based IKE/NAT-T flows.

### Default Drop Protection

After customer-specific rules, the muxer drops unclassified IPsec traffic to the shared public edge:

```bash
iptables -A MUXER_FILTER -i <pub_if> -d 54.204.221.89 -p udp --dport 500 -j DROP
iptables -A MUXER_FILTER -i <pub_if> -d 54.204.221.89 -p udp --dport 4500 -j DROP
iptables -A MUXER_FILTER -i <pub_if> -d 54.204.221.89 -p 50 -j DROP
iptables -A MUXER_FILTER -i <pub_if> -d 172.31.42.35 -p udp --dport 500 -j DROP
iptables -A MUXER_FILTER -i <pub_if> -d 172.31.42.35 -p udp --dport 4500 -j DROP
iptables -A MUXER_FILTER -i <pub_if> -d 172.31.42.35 -p 50 -j DROP
```

Meaning:

- Only traffic that matched a known customer path is allowed through the muxer.

## NAT-T VPN Head-End Configuration

The NAT head end uses strongSwan.

Customer `0003` renders to the following `swanctl` connection:

```text
connections {
  vpn-customer-stage1-15-cust-0003 {
    version = 2
    local_addrs = %any
    remote_addrs = 3.215.115.178
    mobike = no
    fragmentation = yes
    encap = yes
    proposals = aes256-sha256-modp4096,aes256-sha256-modp2048
    dpd_delay = 10s
    local {
      auth = psk
      id = 54.204.221.89
    }
    remote {
      auth = psk
      id = 3.215.115.178
    }
    children {
      vpn-customer-stage1-15-cust-0003-child {
        mode = tunnel
        local_ts = 172.31.54.39/32
        remote_ts = 10.129.3.154/32
        esp_proposals = aes256-sha256-modp4096,aes256-sha256-modp2048
        dpd_action = restart
        policies_fwd_out = yes
        if_id_in = 41003
        if_id_out = 41003
        start_action = start
      }
    }
  }
}
```

What each major statement means:

- `encap = yes`
  This is a NAT-T customer and belongs on the NAT head-end cluster.
- `local.id = 54.204.221.89`
  The head end presents the shared public VPN identity to the customer.
- `remote_addrs = 3.215.115.178`
  The customer peer IP.
- `local_ts = 172.31.54.39/32`
  The demo/core host on our side of the tunnel.
- `remote_ts = 10.129.3.154/32`
  The customer-side source being tested through the tunnel.
- `esp_proposals = aes256-sha256-modp4096,aes256-sha256-modp2048`
  The current CHILD SA proposals, including PFS groups. These must match the customer-side Libreswan expectations.
- `if_id_in = 41003`, `if_id_out = 41003`
  Bind this customer to its dedicated XFRM interface ID.
- `start_action = start`
  Bring the CHILD SA up immediately.

## Head-End XFRM and Policy Routing

The NAT head end creates a per-customer XFRM interface for return-path isolation.

Example script:

```bash
modprobe xfrm_interface >/dev/null 2>&1 || true
ip link add xfrm-c0103 type xfrm if_id 41003
ip link set xfrm-c0103 up
sysctl -w net.ipv4.conf.xfrm-c0103.rp_filter=0
sysctl -w net.ipv4.conf.xfrm-c0103.src_valid_mark=1
ip rule add fwmark 0x41003/0xffffffff table 41003
ip route replace 10.129.3.154/32 dev xfrm-c0103 table 41003
```

Meaning:

- `xfrm-c0103`
  Dedicated interface representing customer `0003`'s return IPsec path.
- `rp_filter=0`
  Prevent reverse-path filtering from killing asymmetric marked traffic.
- `src_valid_mark=1`
  Make the mark part of reverse-path validation.
- `ip rule add fwmark ...`
  Packets marked for customer `0003` use route table `41003`.
- `ip route replace ... dev xfrm-c0103`
  Traffic destined back to `10.129.3.154/32` goes into the customer's XFRM path.

## Post-IPsec NAT for Overlap Handling

Customer `0003` uses overlap-preserving post-IPsec NAT.

Inputs:

- Real customer-side source being tested: `10.129.3.154/32`
- Core/demo destination: `172.31.54.39/32`
- Customer-specific translated internal block: `172.30.0.64/27`
- Output mark: `0x41003/0xffffffff`

Generated rules:

```bash
iptables -t nat -A POSTROUTING -s 10.129.3.154/32 -d 172.31.54.39/32 -j NETMAP --to 172.30.0.64/27
iptables -t nat -A PREROUTING -s 172.31.54.39/32 -d 172.30.0.64/27 -j NETMAP --to 10.129.3.154/32
iptables -t mangle -I PREROUTING 1 -s 172.31.54.39/32 -d 172.30.0.64/27 -j MARK --set-xmark 0x41003/0xffffffff
iptables -t mangle -I FORWARD 1 -p tcp -s 172.31.54.39/32 -d 10.129.3.154/32 --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1360
```

Meaning:

- `POSTROUTING NETMAP`
  When customer `10.129.3.154` talks to the demo host, translate it into a unique customer block on our side.
- `PREROUTING NETMAP`
  When the demo host replies to that translated block, map it back to the customer's real/test address.
- `PREROUTING MARK`
  Mark return traffic before routing so it goes back through the correct customer tunnel.
- `TCPMSS`
  Clamp MSS so TCP works cleanly across encapsulation overhead.

## End-to-End Packet Walk

### Forward path

1. Customer sends encrypted traffic to `54.204.221.89`.
2. Muxer accepts it in `MUXER_FILTER`.
3. Muxer marks it `0x41003` in `MUXER_MANGLE`.
4. Muxer DNATs it toward backend head end `172.31.40.221` in `MUXER_NAT_PRE`.
5. Linux policy routing on the muxer selects table `41003`.
6. Table `41003` sends the packet into `gre-s15-0003`.
7. NAT head end terminates IKE/IPsec with strongSwan.
8. Decrypted traffic from `10.129.3.154/32` to `172.31.54.39/32` is NETMAPed into `172.30.0.64/27`.
9. Demo host sees a unique translated source from customer `0003`.

### Return path

1. Demo host replies from `172.31.54.39` to `172.30.0.64/27`.
2. Head end marks that reply with `0x41003/0xffffffff` in `PREROUTING`.
3. Head end NETMAPs the translated destination back to `10.129.3.154/32`.
4. Policy routing sends the packet into table `41003`.
5. Table `41003` routes it through `xfrm-c0103`.
6. Packet is re-encrypted and returned through the muxer path.
7. Muxer SNATs the encrypted reply so the customer still sees the shared public VPN identity.

## Why the Design Is Split This Way

### Why the muxer uses marks and GRE

The muxer has one shared public front door. It must identify the customer quickly and fan encrypted traffic out to the correct head-end class.

That makes this a good fit for:

- `iptables MARK`
- `ip rule`
- per-customer route tables
- per-customer GRE tunnels

### Why the head end handles NAT and return-path routing

The head end is where decrypted traffic exists, so this is where overlapping customer networks become real.

That makes the head end responsible for:

- IPsec termination
- overlap NAT
- per-customer XFRM routing
- reply path control

## Operational Summary

### Muxer

- Shared public encrypted edge
- Customer classification
- Per-customer mark
- Per-customer GRE delivery
- Head-end cluster selection

### NAT VPN Head End

- strongSwan IKE/IPsec termination
- XFRM interface per customer where required
- overlap-preserving post-IPsec NAT
- marked return routing back into the correct tunnel

## Example Files for This Customer

- Muxer routing:
  [routing.yaml](/E:/Code1/MUXER3/config/customers/vpn-customer-stage1-15-cust-0003/muxer/routing.yaml)
- Muxer tunnel:
  [tunnel.yaml](/E:/Code1/MUXER3/config/customers/vpn-customer-stage1-15-cust-0003/muxer/tunnel.yaml)
- VPN metadata:
  [ipsec.meta.yaml](/E:/Code1/MUXER3/config/customers/vpn-customer-stage1-15-cust-0003/vpn/ipsec.meta.yaml)
- Post-IPsec NAT:
  [post-ipsec-nat.yaml](/E:/Code1/MUXER3/config/customers/vpn-customer-stage1-15-cust-0003/vpn/post-ipsec-nat.yaml)
- Rendered strongSwan customer config:
  [vpn-customer-stage1-15-cust-0003.conf](/E:/Code1/LOCAL_NOTES/tmp-strongswan-headend-cust34-v4/swanctl/conf.d/vpn-customer-stage1-15-cust-0003.conf)
- Rendered XFRM apply script:
  [vpn-customer-stage1-15-cust-0003-xfrm-apply.sh](/E:/Code1/LOCAL_NOTES/tmp-strongswan-headend-cust34-v4/scripts/vpn-customer-stage1-15-cust-0003-xfrm-apply.sh)
