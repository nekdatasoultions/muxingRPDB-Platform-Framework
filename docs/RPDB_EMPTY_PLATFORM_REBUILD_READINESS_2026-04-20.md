# RPDB Empty Platform Rebuild Readiness - 2026-04-20

## Purpose

This document captures the read-only readiness check for rebuilding the current
RPDB-empty platform instead of fixing the existing nodes in place.

No delete, update, SSH, SSM, customer apply, DynamoDB write, or node mutation was
performed during this check.

## Hard Safety Boundary

Only these five RPDB-empty EC2 nodes are in scope for rebuild:

- `i-0744c6c5d61e62744` - `muxer-single-prod-rpdb-empty-node`
- `i-03bf282fbfb4698fa` - `vpn-headend-nat-graviton-dev-rpdb-empty-headend-a`
- `i-0d542d739bb2a35ef` - `vpn-headend-nat-graviton-dev-rpdb-empty-headend-b`
- `i-0c08e18b0388f94a1` - `vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-a`
- `i-09298c582c81a7a82` - `vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-b`

No other EC2 nodes are approved for deletion or replacement.

Before any destructive action, rerun the instance discovery and abort unless the
candidate EC2 instance set exactly matches the five IDs above.

## Current Instance State

All five scoped nodes are currently `running` with AWS instance and system
status checks reporting `ok`.

| Role | Instance ID | Name | Private IP | AZ | Instance type |
|---|---|---|---|---|---|
| muxer | `i-0744c6c5d61e62744` | `muxer-single-prod-rpdb-empty-node` | `172.31.135.175` | `us-east-1b` | `c8gn.8xlarge` |
| NAT head-end A | `i-03bf282fbfb4698fa` | `vpn-headend-nat-graviton-dev-rpdb-empty-headend-a` | `172.31.40.230` | `us-east-1a` | `c8gn.2xlarge` |
| NAT head-end B | `i-0d542d739bb2a35ef` | `vpn-headend-nat-graviton-dev-rpdb-empty-headend-b` | `172.31.141.230` | `us-east-1b` | `c8gn.2xlarge` |
| non-NAT head-end A | `i-0c08e18b0388f94a1` | `vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-a` | `172.31.40.231` | `us-east-1a` | `c8gn.2xlarge` |
| non-NAT head-end B | `i-09298c582c81a7a82` | `vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-b` | `172.31.141.231` | `us-east-1b` | `c8gn.2xlarge` |

## Owning CloudFormation Stacks

The five nodes are owned by these three RPDB-empty stacks:

| Stack | Status | Scoped EC2 resources |
|---|---|---|
| `muxer-single-prod-rpdb-empty` | `CREATE_COMPLETE` | ASG `muxer-single-prod-rpdb-empty-asg`, currently running `i-0744c6c5d61e62744` |
| `vpn-headend-nat-graviton-dev-rpdb-empty-us-east-1` | `CREATE_COMPLETE` | `HeadendA` = `i-03bf282fbfb4698fa`, `HeadendB` = `i-0d542d739bb2a35ef` |
| `vpn-headend-non-nat-graviton-dev-rpdb-empty-us-east-1` | `CREATE_COMPLETE` | `HeadendA` = `i-0c08e18b0388f94a1`, `HeadendB` = `i-09298c582c81a7a82` |

Destructive work should be stack-driven or stack-aware. Do not manually delete
random EC2 nodes by tag or name pattern.

## Important Rebuild Notes

The muxer is Auto Scaling Group backed:

- ASG: `muxer-single-prod-rpdb-empty-asg`
- desired capacity: `1`
- min: `1`
- max: `2`
- launch template: `lt-064441ffd75b88f64`

The head-end nodes are direct CloudFormation EC2 instance resources.

The muxer public IP observed during discovery was `54.86.207.53`. A read-only
Elastic IP lookup returned no allocation for that address. Treat this as an
ephemeral public IP unless a later check proves otherwise. Rebuilding the muxer
may therefore change the muxer public IP.

## Datastore State

Read-only scans showed the RPDB-empty customer tables have no items:

| Table | Count | Scanned count |
|---|---:|---:|
| `muxingplus-customer-sot-rpdb-empty` | `0` | `0` |
| `muxingplus-customer-sot-rpdb-empty-allocations` | `0` | `0` |

These customer tables are not part of the node-delete allow-list.

## Artifact Prefix State

Read-only S3 listing for the RPDB-empty customer deploy prefix returned no
objects:

```text
s3://baines-networking/Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/customer-deploy
```

## Recommended Rebuild Path

Recommended path:

1. Re-run the pre-delete discovery.
2. Confirm the candidate EC2 instance set exactly matches the five scoped IDs.
3. Confirm the three stack names exactly match the stack allow-list.
4. Delete/redeploy only the three RPDB-empty stacks listed above, or use the
   repo platform wrapper if it performs the same stack-scoped action.
5. Do not delete customer SoT or allocation tables unless a separate explicit
   database reset is approved.
6. After rebuild, update `muxer/config/deployment-environments/rpdb-empty-live.yaml`
   with the new instance IDs and IPs if they changed.
7. Run EC2 status checks.
8. Run live-readiness checks for `nft`, muxer runtime, strongSwan/swanctl, and
   required mounts/services.
9. Rerun the Customer 2 and Customer 4 repo dry-runs.
10. Stop before customer apply.

## Pre-Delete Abort Conditions

Abort before destructive action if any of these are true:

- a candidate delete set contains any EC2 instance outside the five scoped IDs
- either RPDB-empty customer table has nonzero customer data
- the customer deploy S3 prefix contains unexpected customer artifacts
- CloudFormation discovery returns a stack outside the three-stack allow-list
- the muxer public IP must be preserved but no Elastic IP plan exists
- the operator has not explicitly approved the delete/recreate command

## Result

The read-only readiness check supports rebuilding the RPDB-empty platform, but
the next step is still an approval gate. No destructive command has been run.

