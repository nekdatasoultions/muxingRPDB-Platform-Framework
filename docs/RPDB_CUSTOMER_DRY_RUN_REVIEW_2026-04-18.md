# RPDB Customer Dry-Run Review 2026-04-18

## Purpose

Record the repo-only customer artifact preparation and dry-run review completed
after the clean RPDB-empty platform redeploy.

This review stops before any live customer apply.

## Environment Used

- deployment environment:
  - `muxer/config/deployment-environments/rpdb-empty-live.yaml`
- platform:
  - `muxer-single-prod-rpdb-empty`
  - `vpn-headend-nat-graviton-dev-rpdb-empty-us-east-1`
  - `vpn-headend-non-nat-graviton-dev-rpdb-empty-us-east-1`
- customer SoT table:
  - `muxingplus-customer-sot-rpdb-empty`
- allocation table:
  - `muxingplus-customer-sot-rpdb-empty-allocations`

## Reviewed Customers

### Customer 2

- request:
  - `muxer/config/customer-requests/migrated/legacy-cust0002.yaml`
- expected path:
  - default strict non-NAT
- dry-run result:
  - `dry_run_ready`
- selected head-end family:
  - `non_nat`
- selected targets:
  - muxer: `muxer-single-prod-rpdb-empty-node`
  - active head-end: `vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-a`
  - standby head-end: `vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-b`
- allocated resources:
  - customer ID: `2000`
  - fwmark: `0x2000`
  - route table: `2000`
  - RPDB priority: `1000`
  - tunnel key: `2000`
  - interface: `gre-cust-2000`
  - overlay block: `169.254.0.0/30`
- review result:
  - bundle manifest present
  - bundle checksums present
  - double verification ready
  - no dynamic NAT-T promotion used

### Customer 4

- request:
  - `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0004.yaml`
- NAT-T observation:
  - `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0004-nat-t-observation.json`
- expected path:
  - dynamic NAT-T promotion to NAT head-end family
- dry-run result:
  - `dry_run_ready`
- selected head-end family:
  - `nat`
- selected targets:
  - muxer: `muxer-single-prod-rpdb-empty-node`
  - active head-end: `vpn-headend-nat-graviton-dev-rpdb-empty-headend-a`
  - standby head-end: `vpn-headend-nat-graviton-dev-rpdb-empty-headend-b`
- allocated resources:
  - customer ID: `41000`
  - fwmark: `0x41000`
  - route table: `41000`
  - RPDB priority: `11000`
  - tunnel key: `41000`
  - interface: `gre-vpn-41000`
  - overlay block: `169.254.128.0/30`
- review result:
  - bundle manifest present
  - bundle checksums present
  - double verification ready
  - dynamic NAT-T promotion planned
  - promotion audit tree generated under:
    - `build/customer-deploy/vpn-customer-stage1-15-cust-0004/package/dynamic-nat-t`

## Common Dry-Run Findings

- both dry-runs stopped before live apply
- both dry-runs reported:
  - no live nodes touched
  - no DynamoDB writes
  - no AWS mutation from the customer deploy orchestrator
- backup references, rollout owners, bundle manifest, and checksum gates all
  passed
- environment access method is currently modeled as `ssh` for the live RPDB
  empty platform contract

## Ready State

The repo is now ready for the next human gate:

1. pick which reviewed customer to apply first
2. review the generated execution plan and bundle contents
3. stop again before any live apply until explicit approval is given
