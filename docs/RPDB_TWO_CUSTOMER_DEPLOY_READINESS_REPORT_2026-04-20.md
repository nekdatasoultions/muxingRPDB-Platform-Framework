# RPDB Two-Customer Deploy Readiness Report - 2026-04-20

## Purpose

This report captures the Phase 1 through Phase 7 repo-only readiness pass for
deploying two pilot customers through the RPDB one-command customer workflow.

The two customers are:

- `legacy-cust0002`
- `vpn-customer-stage1-15-cust-0004`

Customer 3 variants remain blocked and were not used.

## Boundary

This pass did not touch AWS, live nodes, live DynamoDB tables, live nftables
rulesets, live strongSwan state, customer devices, Elastic IPs, or MUXER3.

All generated artifacts were created under:

```text
build/two-customer-readiness/
```

Live apply remains blocked until explicit approval.

## Source Baseline

- Branch: `main`
- Remote: `origin/main`
- Baseline commit for the final run: `d2fdbbd Align active RPDB docs with nftables-only guardrail`
- Environment contract: `muxer/config/deployment-environments/rpdb-empty-live.yaml`
- Customer 2 request: `muxer/config/customer-requests/migrated/legacy-cust0002.yaml`
- Customer 4 request: `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0004.yaml`
- Customer 4 NAT-T observation: `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0004-nat-t-observation.json`

## Target Nodes For Approved Deploy

The dry-run execution plans selected these RPDB-managed targets from
`rpdb-empty-live`.

Shared muxer target:

- name: `muxer-single-prod-rpdb-empty-node`
- instance id: `i-0744c6c5d61e62744`
- private IP: `172.31.135.175`
- role: `muxer`

Customer 2 non-NAT head-end targets:

- active name: `vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-a`
- active instance id: `i-0c08e18b0388f94a1`
- active private IP: `172.31.40.231`
- standby name: `vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-b`
- standby instance id: `i-09298c582c81a7a82`
- standby private IP: `172.31.141.231`

Customer 4 NAT head-end targets:

- active name: `vpn-headend-nat-graviton-dev-rpdb-empty-headend-a`
- active instance id: `i-03bf282fbfb4698fa`
- active private IP: `172.31.40.230`
- standby name: `vpn-headend-nat-graviton-dev-rpdb-empty-headend-b`
- standby instance id: `i-0d542d739bb2a35ef`
- standby private IP: `172.31.141.230`

Datastore targets:

- customer SoT table: `muxingplus-customer-sot-rpdb-empty`
- allocation table: `muxingplus-customer-sot-rpdb-empty-allocations`

Artifact target:

- bucket: `baines-networking`
- prefix: `Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/customer-deploy`

Backup references:

- baseline root: `s3://baines-networking/Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/backups/baseline`
- muxer: `s3://baines-networking/Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/backups/baseline/muxer`
- NAT head end: `s3://baines-networking/Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/backups/baseline/nat-headend`
- non-NAT head end: `s3://baines-networking/Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/backups/baseline/non-nat-headend`

## Phase Results

### Phase 1: Repo And Environment Scope

Status: passed.

Validation performed:

- repo was on `main`
- `HEAD` matched `origin/main`
- `rpdb-empty-live` validated with `--allow-live-apply`
- environment validation reported `aws_calls: false`
- environment validation reported `live_node_access: false`
- active RPDB docs were scanned for prohibited firewall instructions

### Phase 2: Platform Contract And Software Expectations

Status: passed with repo-only boundary.

Validation performed:

- environment contract identifies only RPDB-managed targets
- active platform runbooks now use nftables validation commands
- runtime config requires nftables for classification, translation, and bridge
- no live node package inventory was checked in this pass because live node
  access was intentionally not used

The live node package/service check remains the first live-readiness task before
an actual apply window.

### Phase 3: Backup And Rollback Gate

Status: passed for repo contract.

Both dry-runs found:

- baseline backup root present in the environment contract
- muxer backup reference present
- selected head-end backup reference present
- validation owner present
- rollback owner present
- bundle manifest present
- bundle checksums present

### Phase 4: Customer Artifact Preparation

Status: passed.

Customer 2:

- customer name: `legacy-cust0002`
- selected class: `strict-non-nat`
- selected head-end family: `non_nat`
- fwmark: `0x2000`
- route table: `2000`
- RPDB priority: `1000`
- tunnel interface: `gre-cust-2000`
- tunnel key: `2000`
- overlay block: `169.254.0.0/30`

Customer 4:

- customer name: `vpn-customer-stage1-15-cust-0004`
- selected class: `nat`
- selected head-end family: `nat`
- dynamic NAT-T observation used: `true`
- fwmark: `0x41000`
- route table: `41000`
- RPDB priority: `11000`
- tunnel interface: `gre-vpn-41000`
- tunnel key: `41000`
- overlay block: `169.254.128.0/30`

The operator did not manually select muxer or head-end targets. Target selection
came from the environment contract and generated package metadata.

### Phase 5: Dry-Run Review

Status: passed.

Customer 2 execution plan:

```text
build/two-customer-readiness/legacy-cust0002/execution-plan.json
```

Customer 4 execution plan:

```text
build/two-customer-readiness/vpn-customer-stage1-15-cust-0004/execution-plan.json
```

Validation performed:

- Customer 2 dry-run status: `dry_run_ready`
- Customer 2 live gate status: `dry_run_ready`
- Customer 2 selected head-end family: `non_nat`
- Customer 4 dry-run status: `dry_run_ready`
- Customer 4 live gate status: `dry_run_ready`
- Customer 4 selected head-end family: `nat`
- Customer 4 NAT-T promotion status: `planned`
- package validation passed for both bundles
- muxer customer validation passed for both bundles
- muxer firewall backend was `nftables` for both bundles
- generated readiness artifacts contained no prohibited firewall, legacy repo,
  or Customer 3 tokens

### Phase 6: Staged Apply And Rollback Rehearsal

Status: passed.

Staged roots:

- backend: `build/two-customer-readiness/staged/backend`
- muxer: `build/two-customer-readiness/staged/muxer`
- non-NAT head end: `build/two-customer-readiness/staged/headend-nonnat`
- NAT head end: `build/two-customer-readiness/staged/headend-nat`

Validation performed:

- Customer 2 staged backend apply passed
- Customer 2 staged muxer apply passed
- Customer 2 staged non-NAT head-end apply passed
- Customer 4 staged backend apply passed
- Customer 4 staged muxer apply passed
- Customer 4 staged NAT head-end apply passed
- staged validation passed for backend, muxer, and head end for both customers
- Customer 4 targeted rollback removed only Customer 4
- Customer 2 remained present and valid after Customer 4 rollback
- Customer 2 final rollback removed Customer 2
- final staged rollback cleanup left no staged customer roots behind
- staged artifacts contained no prohibited firewall, legacy repo, or Customer 3
  tokens

### Phase 7: Final Pre-Deploy Review

Status: ready for human review.

The two customer packages are ready for a deploy approval review. The next
action is not automatic deployment. The next action is to review:

- `build/two-customer-readiness/legacy-cust0002/execution-plan.json`
- `build/two-customer-readiness/vpn-customer-stage1-15-cust-0004/execution-plan.json`
- `build/two-customer-readiness/legacy-cust0002/package/bundle/manifest.txt`
- `build/two-customer-readiness/vpn-customer-stage1-15-cust-0004/package/bundle/manifest.txt`
- generated rollback artifacts in each package

## Final Stop Gate

Do not deploy either customer until:

- live node reachability is checked
- `nft` is verified on the muxer and selected head ends
- strongSwan/swanctl is verified on the selected head ends
- the current live backup locations are confirmed reachable
- the operator approves the exact apply window

Recommended deployment order after approval:

1. Deploy `legacy-cust0002`.
2. Validate muxer classification, GRE/RPDB route, non-NAT head-end config, and
   bidirectional traffic.
3. Deploy `vpn-customer-stage1-15-cust-0004`.
4. Validate NAT-T selection, NAT head-end config, post-IPsec NAT, and
   bidirectional traffic.
5. If either customer fails validation, roll back only that customer and stop.

## Result

Repo-only Phase 1 through Phase 7 readiness is complete for the two-customer
deploy packet.
