# RPDB Demo Today

Date: May 12, 2026

## What We Are Showing

Today we are demonstrating the RPDB customer provisioning platform as an
operational workflow, not a hand-built VPN lab. The customer YAML defines the
intent, the MOM/jump host turns that intent into deployable artifacts, and the
platform applies, verifies, reapplies, and removes the customer state across the
muxer, VPN head ends, SmartConnectGateway3, and CGNAT devices.

## Demo Topics

| Area | What We Will Show |
| --- | --- |
| Customer provisioning | A customer request is deployed through the supported customer deployment scripts. |
| Clean remove and reapply | Customers can be removed, verified clean, and provisioned again using the same workflow. |
| Muxer traffic steering | The muxer installs customer-specific routing, GRE, fwmark, and nftables state. |
| Regular non-NAT VPN | A standard customer can be provisioned without NAT translation. |
| NAT-T promotion | The customer starts on non-NAT, the muxer observes UDP 4500, and the watcher promotes the customer to the NAT-T head end. |
| Inside NAT | Customer-side overlapping or translated networks are handled with post-IPsec NAT on the head end. |
| Outside NAT | Backend/service IP presentation is translated so the customer sees the expected service address. |
| Certificate authentication | Customer 4 uses certificate-based IPsec authentication instead of PSK. |
| Local PSK option | Customer 2 shows a demo-safe local PSK flow without requiring AWS Secrets Manager for that test case. |
| SmartConnectGateway3 routing | SmartConnect receives only safe route intent: `remote_host_cidrs` or `translated_subnets`, not broad overlapping `remote_subnets`. |
| Dynamic public IP change | Customer-side check-in updates the dynamic IP service, and the MOM watcher can reapply the customer with the new peer IP. |
| CGNAT per-customer outer | A CGNAT customer owns its own outer certificate tunnel into the CGNAT head end. |
| CGNAT shared ISP gateway | An ISP gateway owns the shared outer tunnel while the customer owns the inner VPN tunnel. |
| Rollback guard rails | The workflow stages artifacts, validates inputs, checks backups, and supports rollback/removal. |

## Planned Demo Profiles

| Profile | Purpose |
| --- | --- |
| `customer2-local-psk` | Local PSK plus NAT-T auto-promotion. |
| `customer4-certificate` | Certificate-authenticated customer VPN. |
| `customer5-inside-nat-explicit-map` | Inside NAT with explicit one-to-one host mappings. |
| Customer 1 style NAT | Inside NAT and outside NAT behavior on the non-NAT head end. |
| `cgnat-provided-per-customer-outer` | CGNAT with customer-owned outer certificate tunnel. |
| `cgnat-provided-shared-isp-gateway` | CGNAT with shared ISP gateway outer tunnel. |

## Simple Talk Track

The key message is that RPDB is now a repeatable provisioning framework. We are
not logging into routers and hand-editing VPNs. We define the customer once,
generate the exact routing, nftables, IPsec, certificate, NAT, SmartConnect, and
CGNAT artifacts, then use the same scripts for deploy, reapply, verify, and
remove.

