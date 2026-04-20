# Troubleshooting Runbook: Muxer + Per-Customer + Cisco + strongSwan

Version: v1  
Date: 2026-03-06  
Scope: How troubleshooting was performed during this project across muxer, Cisco 8000V/C1111, and strongSwan nodes.

## 1. Goal of troubleshooting

For each customer, determine where failure occurs in this chain:

1. Customer initiates IKE/IPsec
2. Muxer receives and classifies traffic
3. Transport handoff path carries packets (GRE/IPIP or local termination path)
4. Cisco/strongSwan processes IKE/CHILD SA
5. Data plane encrypt/decrypt counters increase both directions

Success criterion:

- IKE SA established
- CHILD/ESP SA established
- `encap` and `decap` counters increment on both ends
- application traffic passes

## 2. Per-customer baseline checklist

Before any deep debug, validate per-customer inputs:

- peer public IP (exact /32)
- local/remote IDs
- PSK/cert for that customer
- IKE/ESP proposal parity (DH group, encryption, integrity/PRF)
- traffic selectors / ACL symmetry
- protocol class:
  - strict: `udp/500 + esp/50` only
  - NAT-capable: includes `udp/4500`

If these are wrong, stop and fix before packet-level troubleshooting.

## 3. Muxer troubleshooting process

## 3.1 Control-plane validation

Commands used:

```bash
sudo /etc/muxer/src/muxctl.py show
sudo /etc/muxer/src/muxctl.py apply
ip -br a
ip -d tunnel show
ip rule show
ip route show table <table-id>
```

What we verified:

- correct per-customer interface exists (`gre-cust-xxxx` or `ipip-cust-xxxx`)
- interface is `UP`
- per-customer mark/table policy is installed
- route table default points to the expected customer tunnel

## 3.2 Firewall/classifier validation

Commands used:

```bash
sudo iptables -t mangle -S MUXER_MANGLE
sudo iptables -t mangle -S MUXER_MANGLE_POST
sudo iptables -t nat -S MUXER_NAT_PRE
sudo iptables -t nat -S MUXER_NAT_POST
sudo iptables -S MUXER_FILTER
sudo iptables -L MUXER_FILTER -n -v
```

What we verified:

- per-customer allow rules exist for expected protocols
- `DROP` rules are not shadowing intended peer permits
- packet counters move on the intended customer rules

## 3.3 Packet capture workflow

Always capture at two points to isolate location of failure:

1. ingress interface (`ens5`/public)
2. customer handoff interface (`gre-cust-*` or `ipip-cust-*`)

Commands used:

```bash
sudo tcpdump -ni ens5 'host <peer_ip> and (udp port 500 or udp port 4500 or proto 50)' -vv
sudo tcpdump -ni <cust_tunnel_if> 'host <peer_ip> and (udp port 500 or udp port 4500 or proto 50)' -vv
```

Interpretation:

- seen on ingress but not on handoff: muxer classification/routing/filter issue
- seen on both ingress and handoff: muxer forwarding path is working; issue is downstream
- seen on handoff from peer only (no return): downstream node not returning or return path broken

## 4. Cisco router troubleshooting process (8000V/C1111)

## 4.1 IKE/IPsec status checks

Commands used:

```cisco
terminal length 0
show crypto ikev2 sa detail
show crypto ipsec sa
show crypto ipsec sa peer <peer_ip>
show crypto session detail
show crypto map interface <ifname>
```

Key interpretation:

- IKE `READY/Negotiation done` with IPsec counters `0/0` means control plane is up but data plane path/policy is wrong.
- `NO_PROPOSAL_CHOSEN` indicates proposal mismatch (DH/PRF/encryption/integrity).
- `TS_UNACCEPTABLE` indicates selector/ACL mismatch.
- `IKEv2 profile not found` indicates profile match conditions are not met (identity/FVRF/peer match).

## 4.2 Route/path checks

Commands used:

```cisco
show ip route vrf <vrf-name>
show ip interface brief
ping vrf <vrf-name> <dst> source <src>
```

What we validated:

- protected host routes point where intended
- peer reachability in front-door VRF exists
- source-specific ping behavior aligns with expected policy path

## 4.3 Platform constraints validation

Observed during troubleshooting:

- `crypto map` on `Tunnel` interfaces is rejected on IOS-XE (non-GDOI case).
- This produced the control-plane/data-plane mismatch scenario when combined with tunnel transport design.

## 4.4 Customer C1111 specific checks

Commands used:

```cisco
show run | sec crypto ikev2|crypto map|access-list
show crypto ipsec sa
show logging | include IKEv2|IPSEC|NO_PROPOSAL|TS_UNACCEPTABLE
```

What we checked:

- map sequence matched intended customer ACL
- ACL selectors were symmetric with 8000V side
- proposal and PFS group matched remote
- customer encaps increased and whether decaps returned

## 5. strongSwan troubleshooting process

## 5.1 Service and SA checks

Commands used:

```bash
sudo ipsec statusall
sudo ipsec status
sudo swanctl --list-sas
sudo swanctl --list-conns
```

What we verified:

- IKE/CHILD SA establishment state
- selected proposals and IDs
- byte/packet counters directionally

## 5.2 Log collection

Commands used:

```bash
sudo journalctl -u strongswan -u charon --since "10 min ago"
sudo journalctl --since "10 min ago" | egrep -i "charon|ikev2|auth|id|identity|shared key|mismatch|failed"
```

Notes from troubleshooting:

- In some images `/var/log/charon.log` did not exist; journal-based logging was required.
- AppArmor denials around `stroke` appeared and obscured useful auth lines in some runs.

## 5.3 Packet-level validation at strongSwan node

Commands used:

```bash
sudo tcpdump -ni any 'host <peer_ip> and (udp port 500 or udp port 4500 or proto 50)' -vv
```

Interpretation:

- retransmits of same message ID indicate missing response or path drop
- malformed/unsupported IKE payload signatures suggest rewrite/encapsulation path corruption

## 6. Per-customer troubleshooting sequence used

For each customer (`cust-0001`, `cust-0002`) the sequence was:

1. Confirm config parity (peer, PSK, IDs, selectors, proposals)
2. Confirm muxer policy objects and tunnel state
3. Start dual-point capture on muxer (ingress + customer handoff)
4. Trigger traffic from customer side (ping/IP SLA or IKE initiate)
5. Check Cisco/strongSwan IKE and IPsec counters
6. Correlate logs to capture timeline (message IDs, NAT detection, TS errors)
7. Adjust only one variable at a time
8. Re-test and record outcome

## 7. Common failure signatures and what they meant

- `NAT is found but it is not supported / NAT-T disabled via cli`  
  NAT exists but strict non-NAT-T policy is configured.

- `NO_PROPOSAL_CHOSEN`  
  Proposal mismatch (often DH group mismatch).

- `TS_UNACCEPTABLE`  
  Selector/ACL mismatch between peers.

- IKE SA up but IPsec counters `0/0`  
  Data plane path does not traverse the policy hook that owns the SA.

- Customer encaps increments but remote decap remains zero  
  One-way forwarding/path/filter mismatch between handoff and termination side.

## 8. What was intentionally avoided during troubleshooting

- Bulk config rewrites without backup
- simultaneous multi-domain changes (muxer + both peers at once)
- destructive resets unrelated to active test case

## 9. Recommended troubleshooting artifacts to preserve each run

- timestamped command transcript
- muxer iptables counter snapshots (before/after test)
- dual-point pcaps (ingress + handoff)
- Cisco `show crypto ikev2 sa detail` and `show crypto ipsec sa peer`
- strongSwan `journalctl` slice and `ipsec statusall`

Store by run ID:

- `run_id`
- customer ID
- peer IP
- proposal set
- selectors
- NAT class (strict vs NAT-capable)
- pass/fail and root-cause label

## 10. Outcome-based decision tree used

1. If peer packet not seen on muxer ingress -> external path/SG/NACL/peer issue.
2. If seen ingress but not handoff -> muxer policy/routing issue.
3. If seen on handoff but no IKE on downstream -> transport/return path issue.
4. If IKE up but TS/proposal errors -> config parity issue.
5. If IKE up and ESP SA up but counters 0 -> policy hook/path architecture issue.

This decision tree was repeatedly used to isolate failures quickly by layer.

## 11. Cisco references mapped to 8000V issues

1. Crypto map on tunnel/port-channel/loopback interface limitations (matches the CLI error observed):
   - [Security for VPNs with IPsec Configuration Guide, IOS XE 16.12.x (Unsupported Interface Types)](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/sec_conn_vpnips/configuration/xe-16-12/sec-sec-for-vpns-w-ipsec-xe-16-12-book.pdf)
   - [Migration to IPsec VTI White Paper (crypto map restrictions and VTI migration)](https://www.cisco.com/c/en/us/products/collateral/ios-nx-os-software/ios-ipsec/white-paper-c11-744879.html)

2. Why route-based IPsec (VTI/tunnel protection) is the supported path when policy crypto-map pathing breaks:
   - [VRF-Aware IPsec, IOS XE 17.x (VTI recommendations and IVRF notes)](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/sec-vpn/b-security-vpn/m_sec-vrf-aware-ipsec-0.html)
   - [Configure a Multi-SA VTI on Cisco IOS XE Router](https://www.cisco.com/c/en/us/support/docs/security-vpn/ipsec-negotiation-ike-protocols/214728-configure-multi-sa-virtual-tunnel-interf.html)

3. NAT detection and NAT-T behavior (relevant to `NAT is found but it is not supported` failures):
   - [Configuring IPsec NAT-Traversal (IOS XE family behavior)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-15/configuration_guide/sec/b_1715_sec_9400_cg/configuring_ipsec_nat_traversal.html)

4. Interpreting IKEv2 debug/notify failures such as proposal and selector mismatch:
   - [Troubleshoot IOS IKEv2 Debugs for Site-to-Site VPN with PSKs](https://www.cisco.com/c/en/us/support/docs/ip/internet-key-exchange-ike/115934-technote-ikev2-00.html)
   - [Understand and Use Debug Commands to Troubleshoot IPsec](https://www.cisco.com/c/en/us/support/docs/security-vpn/ipsec-negotiation-ike-protocols/5409-ipsec-debug-00.html)

5. Additional IOS XE guidance that aligns with GRE/IPsec platform behavior:
   - [IOS XE 3S release notes note on GRE over IPsec support method (tunnel protection recommended)](https://www.cisco.com/c/en/us/td/docs/ios/ios_xe/3/release/notes/asr1k_rn_3s_rel_notes/asr1k_feats_important_notes_34s.html)
