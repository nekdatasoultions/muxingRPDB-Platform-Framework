# nftables Muxer Traffic Steering Examples

## Purpose

This document shows the intended nftables-only muxer pattern for steering VPN
customer traffic into the correct head-end path.

The muxer should classify inbound VPN packets, assign a customer-specific
fwmark, and let Linux RPDB route policy send the packet to the correct GRE or
head-end path.

The examples use RFC documentation addresses only:

- `198.51.100.10` as the muxer public IP
- `10.10.1.10` as the muxer private/public-ENI IP
- `203.0.113.20` as an example strict non-NAT peer
- `203.0.113.30` as an example NAT-T peer
- `203.0.113.40` as an example dynamic customer that starts non-NAT

## Core Flow

```text
customer peer packet arrives on public ENI
nftables matches peer + protocol + destination port
nftables sets customer fwmark
Linux RPDB rule matches fwmark
customer route table sends packet into the correct GRE/head-end path
```

## Key Design Rules

- Use nftables for muxer runtime classification.
- Do not use iptables or iptables-restore for RPDB runtime packet steering.
- Keep customer stack selection automatic.
- Start dynamic customers as strict non-NAT.
- Promote to NAT-T only after observing UDP/4500 from the same peer.
- Let RPDB and route tables steer packets after nftables assigns the mark.

## Example Shared nftables Classifier

```nft
table inet rpdb_muxer {
  set public_destinations {
    type ipv4_addr
    elements = { 198.51.100.10, 10.10.1.10 }
  }

  map udp500_mark {
    type ipv4_addr : mark
    elements = {
      203.0.113.20 : 0x2001,
      203.0.113.30 : 0x41001
    }
  }

  map udp4500_mark {
    type ipv4_addr : mark
    elements = {
      203.0.113.30 : 0x41001
    }
  }

  map esp_mark {
    type ipv4_addr : mark
    elements = {
      203.0.113.20 : 0x2001
    }
  }

  chain prerouting_mangle {
    type filter hook prerouting priority mangle; policy accept;

    iifname "eth0" ip daddr @public_destinations udp dport 500 \
      meta mark set ip saddr map @udp500_mark

    iifname "eth0" ip daddr @public_destinations udp dport 4500 \
      meta mark set ip saddr map @udp4500_mark

    iifname "eth0" ip daddr @public_destinations ip protocol esp \
      meta mark set ip saddr map @esp_mark
  }

  chain forward_filter {
    type filter hook forward priority filter; policy accept;

    ct state established,related accept

    iifname "eth0" ip daddr @public_destinations udp dport 500 accept
    iifname "eth0" ip daddr @public_destinations udp dport 4500 accept
    iifname "eth0" ip daddr @public_destinations ip protocol esp accept

    iifname "eth0" ip daddr @public_destinations udp dport { 500, 4500 } drop
    iifname "eth0" ip daddr @public_destinations ip protocol esp drop
  }
}
```

## Example RPDB Routing Behind nftables

```bash
ip rule add pref 10001 fwmark 0x2001 lookup 2001
ip route add default dev gre-nonnat-0001 table 2001

ip rule add pref 11001 fwmark 0x41001 lookup 41001
ip route add default dev gre-nat-0001 table 41001
```

In this example:

- `203.0.113.20` uses UDP/500 plus ESP and receives mark `0x2001`.
- Mark `0x2001` routes through table `2001` to the strict non-NAT head-end path.
- `203.0.113.30` uses UDP/500 plus UDP/4500 and receives mark `0x41001`.
- Mark `0x41001` routes through table `41001` to the NAT-T head-end path.

## Dynamic NAT-T Observation Example

Before promotion, a dynamic customer starts strict non-NAT. If that same peer
later sends UDP/4500, the muxer should emit an observation event that the RPDB
workflow can use to promote the customer to NAT-T.

This example logs the signal with nftables:

```nft
table inet rpdb_muxer_observe {
  set dynamic_nonnat_peers {
    type ipv4_addr
    elements = { 203.0.113.40 }
  }

  set public_destinations {
    type ipv4_addr
    elements = { 198.51.100.10, 10.10.1.10 }
  }

  chain prerouting_observe {
    type filter hook prerouting priority -160; policy accept;

    iifname "eth0" ip daddr @public_destinations udp dport 4500 \
      ip saddr @dynamic_nonnat_peers \
      log prefix "RPDB_NAT_T_OBS " counter
  }
}
```

The observation service can consume those events, correlate the peer to a
dynamic customer request, and create a NAT-T observation artifact.

## Promotion Result

After a valid NAT-T observation:

- The peer is added to the UDP/4500 nftables mark map.
- The peer receives a NAT-T customer fwmark.
- The RPDB rule for that fwmark sends traffic to the NAT-T route table.
- The NAT-T route table sends traffic to the NAT-T head-end path.
- The operator still does not manually choose NAT-T or non-NAT in the customer
  request.

## Runtime Implementation Note

The repo runtime renderer is expected to generate this style of nftables state
from customer modules and environment bindings. Before live deployment, verify
that the generated nftables model includes:

- UDP/500 peer-to-mark mappings
- UDP/4500 peer-to-mark mappings for promoted NAT-T customers
- ESP peer-to-mark mappings for strict non-NAT customers
- public destination sets for muxer public ingress
- RPDB rules matching the generated marks
- route tables pointing to the correct GRE/head-end path

