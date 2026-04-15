# Pilot Customer Readiness Review

Date: 2026-04-15

Scope: isolated RPDB empty platform only. No real customer was deployed in this
review. The only customer writes were synthetic NAT and non-NAT rehearsal items,
and both were removed before the stage was considered complete.

## Current Go/No-Go

Status: go for pilot planning and customer artifact preparation.

Status: no-go for live customer cutover until a specific pilot customer, change
window, customer-side public IP change, VPN head-end target, backup point, and
rollback path are reviewed together.

Customer 15 remains untouched as the onboarding demo case unless explicitly
changed later.

## Verified Platform State

### Repo and Artifact Boundary

- All code changes were made inside this repo:
  `E:\Code1\muxingRPDB Platform Framework-main`
- The old MUXER3 repo was not modified for this stage.
- The RPDB runtime and platform bundles were rebuilt from this repo and uploaded
  to the RPDB empty-platform S3 artifact paths.
- GitHub `main` includes the verification and platform fixes through commit
  `6f22652`.

### Muxer

- Isolated ASG: `muxer-single-prod-rpdb-empty-asg`
- Current verified instance: `i-0061a5e9ae58da131`
- Current public IP: `54.152.175.96`
- Current private IP: `172.31.143.185`
- Transport ENI B: `eni-0ac7117a3a2551dd4`
- Transport ENI B private IP: `172.31.127.237`
- `muxer.service` is active.
- `muxer-local-converge.timer` is active.
- `/etc/muxer/config/muxer.yaml` points at:
  `muxingplus-customer-sot-rpdb-empty`
- `muxctl.py show` can read the current isolated SoT item:
  `legacy-cust0003`

### VPN Head Ends

Verified nodes:

- NAT A: `i-025b3ba03714ffaf0`, `172.31.40.222`
- NAT B: `i-03abc966bbbfa9b8a`, `172.31.141.222`
- non-NAT A: `i-00eee9a4bee70aafd`, `172.31.40.223`
- non-NAT B: `i-098aecaa91a71baef`, `172.31.141.223`

Verified on all four nodes:

- EC2 instance and system status are OK.
- Cloud-init completed.
- StrongSwan/swanctl is installed.
- `conntrackd` is active.
- `muxingplus-ha` is active.
- `/Shared`, `/LOG`, and `/Application` are mounted.

Known degraded management path:

- SSM Run Command is delayed on A-side nodes.
- B-side nodes are not currently SSM-online.
- The repo verifier now supports an EC2 Instance Connect SSH fallback through
  the muxer and records this explicitly.
- This is acceptable for isolated verification, but should be either fixed or
  explicitly accepted before live cutover operations.

### DynamoDB

Customer SoT table:

- Table: `muxingplus-customer-sot-rpdb-empty`
- Status: `ACTIVE`
- Billing: `PAY_PER_REQUEST`
- Key: `customer_name`
- Post-rehearsal item count: `1`
- Remaining item: `legacy-cust0003`

Resource allocation table:

- Table: `muxingplus-customer-sot-rpdb-empty-allocations`
- Status: `ACTIVE`
- Billing: `PAY_PER_REQUEST`
- Key: `resource_key`
- Post-rehearsal item count: `0`

## Synthetic Rehearsal Results

The rehearsal temporarily wrote one NAT customer and one strict non-NAT
customer, verified the live muxer could read each from DynamoDB, then removed
all synthetic customer and allocation records.

NAT synthetic customer:

- Name: `rpdb-stage4-synthetic-nat`
- Customer ID: `41000`
- fwmark: `0x41000`
- route table: `41000`
- RPDB priority: `11000`
- tunnel key: `41000`
- transport interface: `gre-vpn-41000`
- overlay block: `169.254.128.0/30`
- muxer read verification: passed with `muxctl.py show-customer`

Strict non-NAT synthetic customer:

- Name: `rpdb-stage4-synthetic-nonnat`
- Customer ID: `2000`
- fwmark: `0x2000`
- route table: `2000`
- RPDB priority: `1000`
- tunnel key: `2000`
- transport interface: `gre-cust-2000`
- overlay block: `169.254.0.0/30`
- muxer read verification: passed with `muxctl.py show-customer`

Cleanup verification:

- Synthetic customer records remaining: `0`
- Synthetic allocation records remaining: `0`

## Fixes Made During Verification

- `verify_headend_bootstrap.py` now reads BOM-bearing parameter snapshots and
  can verify services through a muxer EC2 Instance Connect fallback when SSM is
  degraded.
- `ensure_dynamodb_tables.py` now reads BOM-bearing parameter snapshots.
- `cfn_deploy.sh` now reads BOM-bearing parameter snapshots.
- `muxer-single-asg.yaml` now grants muxer instances `dynamodb:GetItem` on the
  configured customer SoT table, which is required by `show-customer`.
- The isolated muxer stack was updated successfully with the IAM fix.

## Pilot Entry Criteria

Before a real customer cutover:

- Choose the pilot customer explicitly.
- Confirm customer 15 remains reserved for the demo flow unless deliberately
  selected.
- Capture backups of current muxer, VPN head-end, route, iptables/nftables, and
  customer-side state.
- Build the customer YAML/request from verified live facts.
- Run provisioning and allocation reservation dry-run.
- Render muxer and head-end artifacts.
- Review the exact customer-side public IP change.
- Review the exact VPN head-end target.
- Review rollback steps tied to the backups.
- Decide whether SSM degradation must be fixed before the live change or
  whether EC2 Instance Connect fallback is an accepted operational path.

## Recommended Next Step

Prepare the first real pilot customer package without applying it:

1. Select the customer.
2. Build the customer request YAML from live facts.
3. Run repo provisioning to produce the allocated customer source, muxer module,
   DynamoDB item, allocation records, and head-end artifacts.
4. Review the generated artifacts and rollback plan.
5. Stop for human approval before any real customer, VPN head-end, or
   customer-side change is applied.
