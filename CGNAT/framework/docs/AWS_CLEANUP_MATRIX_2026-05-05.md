# AWS Cleanup Matrix 2026-05-05

## Purpose

This document classifies the current AWS nodes into:

1. **Keep**
2. **Verify Before Delete**
3. **Manual Migration Queue**

The intent is to clean up the old muxer-era environment without removing nodes
that are part of the current live RPDB-empty CGNAT service path.

## Guard Rails

Before deleting any node:

1. confirm it is **not** referenced by the current deployment contract:
   - `muxer/config/deployment-environments/rpdb-empty-live.yaml`
2. confirm it is **not** part of the live packet path
3. confirm it is **not** the only remaining instance for an older environment
   that still matters operationally
4. confirm current backups exist:
   - `E:\Code1\backups\cgnat-full-backup-20260505T134240`

## Current Keep Set

These nodes are part of the current live environment or the live service path
and should be protected.

| Instance ID | Name | Why it stays |
|---|---|---|
| `i-0c8c34de42777c769` | `muxer-single-prod-rpdb-empty-node` | current RPDB-empty muxer |
| `i-0a5f8a1e1b0fed116` | `vpn-headend-nat-graviton-dev-rpdb-empty-headend-a` | current RPDB-empty NAT head end active |
| `i-026dcd8f4b658772b` | `vpn-headend-nat-graviton-dev-rpdb-empty-headend-b` | current RPDB-empty NAT head end standby |
| `i-05c6a9f56cd531322` | `vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-a` | current RPDB-empty non-NAT head end active |
| `i-0eb58b43b6886ea0c` | `vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-b` | current RPDB-empty non-NAT head end standby |
| `i-07bf5d2d5e74d8238` | `cgnat-head-end-rpdb-empty-a` | current CGNAT head end |
| `i-0c754831882fbe932` | `cgnat-isp-head-end-rpdb-empty-a` | current Scenario 1 ISP/CGNAT outer path |
| `i-0d93ab76eeb8b3a72` | `isp-cgnat-router-2` | current Scenario 2 ISP gateway |
| `i-08beecca2f8ef0802` | `customer-vpn-router-1-rpdb-empty-a` | live Customer 1 / Scenario 1 |
| `i-039ca2e1a904c29af` | `customer-vpn-router-2-rpdb-empty-a` | live Customer 2 / Scenario 2 |
| `i-01edd5f99fe45e99d` | `JUMP-HOST-ANSIBLE-01` | operator/jump path still useful |
| `i-0c1d3acaa37070ed0` | `SmartConnectGateway3` | downstream service path and Customer 1 NAT return path |

## Verify Before Delete

These nodes are not in the current `rpdb-empty-live` contract and still deserve
manual confirmation before removal.

| Instance ID | Name | Why verify first |
|---|---|---|
| `i-002b96b2e50f906ce` | `NetBox-SoT-01` | unrelated to current CGNAT path, but may still matter to operations |

## Retired 2026-05-05

These legacy infrastructure nodes were terminated after backups were taken and
after confirming they were outside the current keep set and outside the legacy
VPN customer migration queue.

| Instance ID | Name |
|---|---|
| `i-0b9501e2561b934a5` | `muxer-single-prod-node` |
| `i-0b645c1e664914002` | `muxer-single-prod-node` |
| `i-0e36a4b5425774b74` | `vpn-headend-nat-graviton-dev-headend-a` |
| `i-042fc7e06b4992e74` | `vpn-headend-nat-graviton-dev-headend-b` |
| `i-03df357b7d4031524` | `vpn-headend-non-nat-graviton-dev-headend-a` |
| `i-077040652765b7928` | `vpn-headend-non-nat-graviton-dev-headend-b` |
| `i-0d6e8714b9a99043e` | `vpn-headend-nat-headend-a` |
| `i-0f1cc1c76ef0a583f` | `vpn-headend-nat-headend-b` |
| `i-0463e6d6906bf6c58` | `vpn-headend-non-nat-headend-a` |
| `i-0d08ca2559bb0438f` | `vpn-headend-non-nat-headend-b` |

## Retired Legacy Stack Control Plane

The legacy single-muxer CloudFormation stack was also retired so that the old
`muxer-single-prod-node` instances would stop respawning through Auto Scaling.

| Resource | Status |
|---|---|
| `muxer-single-prod` CloudFormation stack | delete started on `2026-05-05` |
| `muxer-single-prod-asg` Auto Scaling Group | scaled to zero during stack delete |
| respawned legacy muxer instances | terminated during stack retirement |

## Manual Migration Queue

These look like old stage/demo/customer-era customer nodes and are not part of
the current `rpdb-empty-live` contract.

They should **not** be terminated first.

They should be:

1. manually provisioned or migrated onto the new muxer/backends
2. validated on the new platform path
3. retired only after migration is confirmed

| Instance ID | Name |
|---|---|
| `i-0c894a448beefb8c0` | `vpn-customer-stage1-15-cust-0001` |
| `i-01c74e547dc5175db` | `vpn-customer-stage1-15-cust-0002` |
| `i-0dbce2d460333c4e7` | `vpn-customer-stage1-15-cust-0003` |
| `i-0b52ee7132bf6fa90` | `vpn-customer-stage1-15-cust-0004` |
| `i-0b7093eaf6559df5f` | `vpn-customer-stage1-15-cust-0005` |
| `i-07aadd0c29e44ae8d` | `vpn-customer-stage1-15-cust-0006` |
| `i-0cb1df2891e5e3c9b` | `vpn-customer-stage1-15-cust-0007` |
| `i-0e389e28ebda97fb6` | `vpn-customer-stage1-15-cust-0008` |
| `i-0a878080d2dda41ee` | `vpn-customer-stage1-15-cust-0009` |
| `i-06451d10960d3d3d9` | `vpn-customer-stage1-15-cust-0010` |
| `i-058402769b353cde5` | `vpn-customer-stage1-15-cust-0011` |
| `i-0e6560ebae8bf6f59` | `vpn-customer-stage1-15-cust-0012` |
| `i-06dc9343b9b223f85` | `vpn-customer-stage1-15-cust-0013` |
| `i-0464022485df43409` | `vpn-customer-stage1-15-cust-0014` |
| `i-0e5e20f77cd15ea43` | `vpn-customer-stage1-15-cust-0015` |
| `i-0ec6df241d3ad57ad` | `vpn-microhub-legacy-cust0002` |

## Key Heuristic

The heuristic:

- keep nodes with `muxer.pem` **and** `rpdb` in the name
- keep the jump host
- keep the customer VPN nodes

is **mostly correct**, but it misses two important current-production cases:

1. `isp-cgnat-router-2`
   - does not contain `rpdb`
   - **must stay**
2. `SmartConnectGateway3`
   - does not use the `muxer` keypair
   - **must stay**

## Practical Cleanup Order

1. keep the **Current Keep Set** untouched
2. validate no production dependency on **Verify Before Delete**
3. manually migrate nodes in the **Manual Migration Queue**
4. retire migrated nodes only after validation
5. only then revisit the older muxer/head-end tiers

## Supporting Evidence

Primary current environment contract:

- `E:\Code1\muxingRPDB Platform Framework-main\muxer\config\deployment-environments\rpdb-empty-live.yaml`

Full backup root:

- `E:\Code1\backups\cgnat-full-backup-20260505T134240`
