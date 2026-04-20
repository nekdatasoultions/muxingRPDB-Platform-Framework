# Test Cases And Blocking Dependencies

Date range covered: March 5-6, 2026  
Scope: Muxer + 8000V + strongSwan/C1111 validation performed in this thread  
Change control note: This document creation is repo-only. No device changes were made for this step.

## Environment under test

- Muxer public IP: `54.204.221.89`
- Muxer private underlay (examples seen): `172.31.39.201` (`ens5`)
- 8000V: `172.31.39.200` (front-door VRF side in prior design)
- Customer 1 peer: `54.85.240.35`
- Customer 2 peer: `166.213.153.39`

## Test matrix summary

| ID | Test case | Expected | Observed | Result | Blocking dependency |
|---|---|---|---|---|---|
| TC-001 | Customer 1 IKEv2/IPsec with NAT-T disabled (`udp/500 + esp/50` only) while NAT exists in path | Tunnel up without `udp/4500` | 8000V logs: `NAT is found but it is not supported.: NAT-T disabled via cli` | Failed | IKEv2 NAT detection requires NAT-T when NAT is present |
| TC-002 | Pass-through with UDP/4500 allowed via muxer chains | IKE AUTH and CHILD SA complete | Repeated IKE_AUTH retransmits / repeated CHILD_SA responses, unstable completion | Partial / unstable | End-to-end path and selector/profile mismatches across devices |
| TC-003 | Forced rewrite experiment (`4500 -> 500`) | Bypass NAT-T requirement by rewriting ports | strongSwan received malformed/unsupported IKE (`received unsupported IKE version 13.5`) in one run | Failed | Payload/marker semantics broken by forced rewrite path |
| TC-004 | NAT-D payload rewrite experiment (DPI/NFQUEUE) | Make endpoints believe no NAT and continue on 500 | Intermittent control-plane progress, no reliable data-plane success | Failed / brittle | NAT-D spoofing is fragile and conflicts with standards behavior |
| TC-005 | Per-customer separate IPIP over same local/remote underlay tuple | Two stable parallel customer tunnels | Could not reliably represent duplicate unkeyed tunnel tuples | Failed | Linux unkeyed tunnel tuple collision/ambiguity |
| TC-006 | Keyed GRE per customer over shared underlay (`.201 <-> .200`) | Independent parallel transport tunnels | `gre-cust-0001` and `gre-cust-0002` came up, endpoint pings succeeded | Passed | Requires keyed GRE (or equivalent keyed transport) |
| TC-007 | 8000V crypto-map applied to `Tunnel200x` | Policy IPsec decrypt on tunnel interface | IOS-XE CLI error: only GDOI supported on tunnel/port-channel for crypto map | Failed | Platform limitation: policy crypto map unsupported on tunnel interfaces |
| TC-008 | Keep crypto map on Loopback/front-door while routing protected host via `Tunnel2002` | Data encrypted/decrypted counters increment | IKE SA UP, ESP SA ACTIVE, but `#pkts encaps/decaps` remained `0/0` on 8000V | Failed | Packet path bypassed supported crypto policy hook for actual data flow |
| TC-009 | Customer 2 proposal negotiation with mismatched DH group | SA setup with policy match | `NO_PROPOSAL_CHOSEN` (Group16 offered vs Group14 expected) | Failed | Proposal dependency: DH/encryption/integrity must match exactly |
| TC-010 | Customer 2 IKE_AUTH/TS acceptance | CHILD SA accepted | `% IKEv2 profile not found`, `TS_UNACCEPTABLE` seen in failing iterations | Failed (then improved later) | Profile match/identity/TS ACL alignment dependency |
| TC-011 | Customer 2 SA established and customer encapsulating traffic | Bidirectional packet counters rise on both ends | Customer side encaps increased; 8000V saw inbound ESP on transport capture but no decaps | Failed (data-plane) | Same tunnel-interface/policy-path coupling issue |
| TC-012 | Muxer observability/logging checks | Clear auth/ID/PSK failure reasons | Missing `/var/log/charon.log`; journal output dominated by AppArmor stroke denials | Partial | Logging backend/profile dependencies on distro/service layout |

## Detailed dependencies that stopped tests

## 1) Protocol-level dependencies

- If NAT is detected in IKEv2, NAT-T behavior is required for correct operation.
- Forcing `udp/500 + esp/50` through a NAT path is not reliably achievable by port rewrite tricks.
- IKE proposal parameters must match exactly (DH group, encryption, integrity, PRF).

## 2) Platform dependencies (IOS-XE)

- Policy `crypto map` cannot be attached to tunnel interfaces (except GDOI cases).
- If control plane comes in one interface/VRF context but protected data is routed elsewhere, SA may be UP while data counters remain zero.

## 3) Topology/routing dependencies

- Routes for protected prefixes must direct traffic into the same policy path that owns IPsec processing.
- Mixed use of pass-through transport tunnel and policy crypto map can create "SA up, no payload flow".
- For multi-customer transport over same underlay, keyed tunneling is required to avoid tuple collisions.

## 4) Identity/policy dependencies

- IKE profile match and keyring identity must align with peer address/ID.
- Crypto ACL / TS selectors must be symmetric and reflect actual source/destination protected hosts.
- Any stale duplicate map/profile entries can cause `TS_UNACCEPTABLE`, `PROFILE not found`, or wrong map selection.

## 5) Operational dependencies

- Useful debug requires consistent logging target (systemd journal vs charon file) and correct service profile.
- Packet capture must be done at both ingress and handoff interfaces to separate "not arriving" vs "arriving but not decrypting".

## 6) AWS-specific blockers and dependencies

- **NAT in path forces NAT-T behavior**  
  If any side is behind NAT, strict `udp/500 + esp/50` expectations break. AWS Site-to-Site VPN guidance explicitly calls out UDP/4500 for NAT-T operation.  
  Dependency: customer policy must allow `udp/4500` when NAT exists.

- **NAT Gateway does not carry ESP (`ip proto 50`)**  
  AWS NAT Gateway supports TCP/UDP/ICMP, not raw ESP.  
  Blocker: any architecture that places strict ESP flows through NAT Gateway will fail.

- **EC2 forwarding role requires source/destination check disabled**  
  For a muxer/NAT/router instance forwarding traffic, source/destination check must be disabled.  
  Blocker: if left enabled, transit behavior is dropped by platform policy.

- **Security controls are ENI-scoped and protocol-explicit**  
  Security groups attach to ENIs (not IPs), and rules must permit required protocols (`udp/500`, optional `udp/4500`, `esp/50`). NACLs must match as well.  
  Blocker: missing protocol 50 or 4500 in SG/NACL creates silent one-way behavior.

- **EIP is a 1:1 mapping to private IPv4 on ENI**  
  The instance sees private interface addresses, while external peers target EIP.  
  Dependency: muxer classification/NAT logic must account for private-vs-public destination identity consistently.
- **Strict non-NAT peers should not be deployed on a plain EIP edge by default**  
  The platform still presents a NAT-like edge to the instance and to IKE NAT detection logic.  
  Dependency: use a strict-compatible ingress design such as Internet Gateway ingress routing with BYOIP, or treat the customer as NAT-T capable.

- **Multi-ENI asymmetric routing risk (observed)**  
  In this testbed, dual defaults (`ens5` and `ens6`) existed simultaneously on muxer.  
  Dependency: explicit policy routing is required so return traffic exits the same expected path; otherwise ESP/IKE sessions may flap or blackhole.

- **Encapsulation overhead can trigger MTU/fragmentation issues**  
  GRE/IPIP + ESP + NAT-T overhead reduces effective payload MTU.  
  Dependency: PMTU/MSS/fragmentation handling must be validated per customer path to avoid data-plane loss with SA up.

Reference links (AWS):

- NAT gateway basics and protocol support:  
  <https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html>
- Source/destination check requirements for routing instances:  
  <https://docs.aws.amazon.com/vpc/latest/userguide/work-with-nat-instances.html>
- Security groups attach to ENIs (not IP addresses):  
  <https://docs.aws.amazon.com/AWSEC2/latest/WindowsGuide/using-eni.html>
- Security group protocol fields support protocol numbers:  
  <https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-security-group-rules.html>
- Elastic IP mapping behavior:  
  <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html>
- NAT-T UDP/4500 requirement context (AWS Site-to-Site VPN docs):  
  <https://docs.aws.amazon.com/vpn/latest/s2svpn/VPNTunnels.html>

## 7) Cisco-specific blockers and dependencies (8000V / IOS-XE)

- **Policy crypto map on tunnel interfaces is not supported (except GDOI)**  
  This matches the exact CLI behavior seen during testing when attempting `crypto map` under `Tunnel200x`.  
  Blocker: policy-based decrypt path cannot be moved onto tunnel interfaces in this platform mode.

- **GRE-over-IPsec on IOS-XE is documented as route-based (tunnel protection) workflow**  
  Cisco guidance for GRE over IPsec uses `tunnel protection ipsec profile` rather than policy crypto map attached to the GRE tunnel.  
  Dependency: architecture must align with route-based model when tunnel-interface protection is required.

- **VRF-aware IPsec requires strict FVRF/IVRF alignment**  
  Mismatch between front-door VRF context, IKE profile matching, and inner VRF handling leads to profile and selector failures (`profile not found`, `TS_UNACCEPTABLE` patterns observed).  
  Dependency: peer-facing and inner VRF model must be consistent per tunnel/profile.

- **IKEv2 keyring/identity uniqueness and lookup behavior can constrain multi-peer designs**  
  Cisco docs note responder-side key lookup behavior and identity constraints.  
  Dependency: remote identities and keyring peer entries must be unique and deterministic.

- **NAT detection implies NAT-T behavior in Cisco IKEv2 as well**  
  The observed `NAT is found but it is not supported` errors are consistent with Cisco NAT-T behavior requirements when NAT is present.  
  Dependency: if NAT exists anywhere in path, allow NAT-T-capable handling.

Reference links (Cisco):

- Crypto map interface limitations and policy-IPsec model (IOS XE):  
  <https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/sec_conn_vpnips/configuration/xe-16-12/sec-sec-for-vpns-w-ipsec-xe-16-12-book.pdf>
- VRF-aware IPsec (classic IOS XE reference):  
  <https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/sec_conn_ikevpn/configuration/xe-3s/VRF-Aware_IPsec.html>
- VRF-aware IPsec (IOS XE 17.x security VPN guide):  
  <https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/sec-vpn/b-security-vpn/m_sec-vrf-aware-ipsec-0.html>
- GRE over IPsec configuration model (route-based tunnel protection flow):  
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-16/configuration_guide/sec/b_1716_sec_9300_cg/configuring_gre_over_ipsec.html>
- IKEv2 debug interpretation and failure analysis:  
  <https://www.cisco.com/c/en/us/support/docs/ip/internet-key-exchange-ike/115934-technote-ikev2-00.html>
- IPsec debug usage on Cisco platforms:  
  <https://www.cisco.com/c/en/us/support/docs/security-vpn/ipsec-negotiation-ike-protocols/5409-ipsec-debug-00.html>

## What clearly worked

- Customer ingress classification on muxer (`udp/500`, `udp/4500`, `esp`) with per-customer policy.
- Keyed GRE per-customer transport over shared underlay.
- IKE SA establishment for customer 2 in multiple iterations.

## What did not reliably work

- Eliminating NAT-T in NAT-present paths via rewrite/DPI methods.
- Policy crypto-map data-plane decryption when transport architecture forced packets through tunnel interfaces in IOS-XE.

## Implication for MUXER3 direction

Given constraints above, removing 8000V from data path and terminating per-customer IPsec on muxer-side isolated instances (containers/netns) is the cleanest path to:

- support overlapping tenant IP space
- keep per-customer policy isolation
- avoid IOS-XE tunnel-interface crypto-map limitation

while still respecting protocol reality: NATed customers require NAT-T-capable handling.
