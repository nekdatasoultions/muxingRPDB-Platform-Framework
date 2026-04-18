# RPDB Fresh Addressing Proposal 2026-04-18

## Purpose

This document records the executed Phase 1 through Phase 3 work for the fresh
RPDB address plan.

The previous prepared `rpdb-empty` parameter set could not be redeployed
because it reused private IPs that are already attached to live stacks in the
same VPC.

## Scope

- repo: `E:\Code1\muxingRPDB Platform Framework-main`
- out of scope: `E:\Code1\MUXER3`
- account: `594085074402`
- region: `us-east-1`
- VPC: `vpc-0f74bd28e5a4239a2`

## Phase 1 Inventory Summary

Relevant subnets:

- public A: `subnet-04a6b7f3a3855d438` `172.31.32.0/20`
- public B: `subnet-0cc9697bd58c319ec` `172.31.128.0/20`
- transport A: `subnet-038b60ae13426a83a` `172.31.64.0/20`
- transport B: `subnet-0577ac1a6d0ff5930` `172.31.112.0/20`
- core A: `subnet-0dbd0842618d43ab3` `172.31.48.0/20`
- core B: `subnet-0e6ae1d598e08d002` `172.31.80.0/20`

Live stack conflicts that blocked the old prepared parameters:

- `muxer-single-prod`
  - `172.31.69.213`
  - `172.31.127.236`
- `vpn-headend-nat-graviton-dev-us-east-1`
  - `172.31.40.221`
  - `172.31.141.221`
  - `172.31.75.121`
  - `172.31.113.121`
  - `172.31.55.121`
  - `172.31.88.121`
- `vpn-headend-non-nat-graviton-dev-us-east-1`
  - `172.31.40.220`
  - `172.31.141.220`
  - `172.31.69.220`
  - `172.31.113.220`
  - `172.31.59.220`
  - `172.31.89.220`

Non-IP prerequisites that are currently valid:

- AMI `ami-0b11e0ed3f8697f97`
- key pair `muxer`
- EFS `fs-00e2b6fc15df408dc`
- EFS access point `fsap-07305fb7c753b1ad8`
- bundle targets under
  `s3://baines-networking/Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/`

## Phase 2 Proposed Private IP Matrix

### Muxer

- transport ENI A: `172.31.69.232`
- transport ENI B: `172.31.127.232`
- NAT active A underlay reference: `172.31.40.230`
- NAT active B underlay reference: `172.31.141.230`
- non-NAT active A underlay reference: `172.31.40.231`
- non-NAT active B underlay reference: `172.31.141.231`

### NAT Head-End Pair

- node A primary: `172.31.40.230`
- node B primary: `172.31.141.230`
- node A HA/sync: `172.31.75.230`
- node B HA/sync: `172.31.113.230`
- node A core: `172.31.55.230`
- node B core: `172.31.88.230`

### Non-NAT Head-End Pair

- node A primary: `172.31.40.231`
- node B primary: `172.31.141.231`
- node A HA/sync: `172.31.69.231`
- node B HA/sync: `172.31.113.231`
- node A core: `172.31.59.231`
- node B core: `172.31.89.231`

## Phase 3 Validation Result

All proposed private IPs were checked directly against live EC2 network
interfaces and were unused at validation time.

Validated clear:

- `172.31.69.232`
- `172.31.127.232`
- `172.31.40.230`
- `172.31.141.230`
- `172.31.75.230`
- `172.31.113.230`
- `172.31.55.230`
- `172.31.88.230`
- `172.31.40.231`
- `172.31.141.231`
- `172.31.69.231`
- `172.31.113.231`
- `172.31.59.231`
- `172.31.89.231`

## EIP Note

The account currently has an EC2-VPC Elastic IP quota of `30`, and `30`
addresses are already allocated.

Current unassociated EIPs: `2`

- `eipalloc-05805cf589603f894` `100.30.83.15`
- `eipalloc-0c1769dbbdd3526c1` `23.20.31.151`

Because the quota is full, the clean proposal for the empty-platform redeploy
is:

- keep `EipAllocationId` blank during empty-platform stand-up
- bring the private-IP-based platform up first
- handle fresh dedicated RPDB EIPs as a separate follow-on step before any
  public/customer cutover

This avoids reusing unrelated project EIPs and avoids blocking the empty
platform on EIP quota work.

## Gate Status

- Phase 1 inventory: passed
- Phase 2 private IP proposal: passed
- Phase 3 private IP conflict validation: passed
- EIP requirement for three fresh dedicated addresses: deferred due to quota
  saturation

## Next Step

Update the prepared `rpdb-empty` parameter files to this private IP matrix,
keep `EipAllocationId` blank, run dry-run deploy validation, and only then
retry the empty-platform redeploy.

## Execution Result

The prepared parameter files were updated to the proposed private IP matrix and
dry-run validation passed.

Live redeploy result:

- muxer stack deploy: passed
- NAT head-end deploy: failed before CloudFormation stack creation
- non-NAT head-end deploy: not attempted because execution stopped at the NAT
  failure

Current live state after the stopped run:

- `muxer-single-prod-rpdb-empty`: created successfully
- `vpn-headend-nat-graviton-dev-rpdb-empty-us-east-1`: not created
- `vpn-headend-non-nat-graviton-dev-rpdb-empty-us-east-1`: not created
- customer SoT table: not yet created in this run
- allocation table: not yet created in this run

## Problem Statement

The gate failure is not caused by the new private IP proposal.

The failure occurs inside the shared deploy helper:

- `scripts/platform/cfn_deploy.sh`

The helper validates subnet CIDRs before CloudFormation deploy by reading the
output of:

- `aws ec2 describe-subnets --output text`

In the current execution environment, the last CIDR string retains a trailing
carriage return, for example:

- `172.31.128.0/20\r`

That value is then passed into Python `ipaddress.ip_network(...)`, which raises:

- `ValueError: '172.31.128.0/20\\r' does not appear to be an IPv4 or IPv6 network`

Because of that:

- the NAT head-end deploy script exits before CloudFormation submission
- the NAT stack is never created
- the non-NAT deploy is never reached

## Root Cause Summary

The addressing gate is now clear, but the platform deploy helper has a
cross-environment line-ending parsing bug in the VPN head-end deploy path.

This is a repo-side script issue in the deploy wrapper layer, not an AWS IP
conflict and not a CloudFormation template rejection.

## Resolution Plan For The Next Session

1. Fix `scripts/platform/cfn_deploy.sh` so subnet CIDRs are normalized before
   Python validation.
2. Re-run the NAT head-end deploy.
3. Re-run the non-NAT head-end deploy.
4. Ensure the customer SoT table exists.
5. Run empty-platform validation across muxer, both head-end pairs, and the
   database.

## Restart Point

Resume from the head-end deploy wrapper failure, not from address planning.

The private IP proposal and prepared parameter files are already updated and
validated for zero overlap.

## Resolution Outcome

The repo-side deploy wrapper issue was fixed by normalizing subnet CIDR text in:

- `scripts/platform/cfn_deploy.sh`

After that fix:

- the NAT head-end deploy succeeded
- the non-NAT head-end deploy succeeded
- the RPDB customer SoT table was created with the prepared RPDB-empty name
- the RPDB allocation table was created with the prepared RPDB-empty name

The current stack state is:

- `muxer-single-prod-rpdb-empty`: `CREATE_COMPLETE`
- `vpn-headend-nat-graviton-dev-rpdb-empty-us-east-1`: `CREATE_COMPLETE`
- `vpn-headend-non-nat-graviton-dev-rpdb-empty-us-east-1`: `CREATE_COMPLETE`

The current database state is:

- `muxingplus-customer-sot-rpdb-empty`: `ACTIVE`, item count `0`
- `muxingplus-customer-sot-rpdb-empty-allocations`: `ACTIVE`, item count `0`

## Current Validation State

Empty-platform readiness now passes when verified with the RPDB muxer as the
SSH bastion fallback.

Validated:

- all four VPN head-end nodes are EC2 healthy
- all four VPN head-end nodes passed service verification
- `/Shared`, `/LOG`, and `/Application` are mounted on all four nodes
- `conntrackd` and `muxingplus-ha` are active on all four nodes
- the RPDB-empty SoT and allocation tables both exist and are empty

Important nuance:

- SSM is still degraded on the `b` nodes, so the clean validated path today is:
  - verify through `verify_headend_bootstrap.py` using
    `--ssh-fallback-bastion-instance-id <rpdb-muxer-instance-id>`

## New Restart Point

Resume from customer artifact preparation or from any optional work to improve
SSM on the `b` nodes.

Do not resume from address planning or empty-platform redeploy unless the RPDB
stack is intentionally replaced again.
