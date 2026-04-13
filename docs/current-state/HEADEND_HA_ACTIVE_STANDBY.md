# VPN Head-End Active/Standby Model (ASA-like)

## Objective

Provide high availability for VPN head-end behavior with clear ACTIVE and STANDBY roles.

## Behavior Target

- Only one node is ACTIVE at a time.
- ACTIVE node owns ingress identity (EIP/ENI attachment model).
- STANDBY node remains warm and ready, but not forwarding production VPN traffic.
- Failover is automatic using a lease-based election.

## Control Plane

### Leader Election

- Backend: AWS DynamoDB single-row lease.
- Lease item identifies current holder and expiry timestamp.
- ACTIVE node must continuously renew lease.
- If lease expires, other node can acquire and promote itself.

### Role State

Role state file:
- `/run/muxingplus-ha/role.state`

Valid values:
- `active`
- `standby`

## Data Plane Role Actions

### Promote (active)

- Associate EIP to local ENI (optional, if configured).
- Start or reload IPsec stack.
- Start customer termination services (optional script hook).
- Run custom active hook.
- Trigger flow-sync promote hook (when `FLOW_SYNC_MODE=conntrackd`).

### Demote (standby)

- Stop customer termination services (optional script hook).
- Stop IPsec stack (or keep passive per policy).
- Run custom standby hook.
- Trigger flow-sync demote hook (when `FLOW_SYNC_MODE=conntrackd`).

## Sync Layers

1. Flow-state layer:
   - `conntrackd` for connection/NAT state sync on muxers.
2. SA-state layer:
   - `libreswan-no-sa-sync` (failover with re-negotiate)
   - `strongswan-ha` (SA sync plugin model)

## Suggested Timers

- Election loop interval: 3 seconds
- Lease TTL: 15 seconds

This gives fast failover while avoiding lease flapping in normal jitter.

## ASA-Like vs Open-Source HA Caveat

This design matches ASA-style **role failover** (active/standby ownership), but not necessarily full in-memory SA/session state mirroring.

Result:
- Existing active sessions may re-establish after failover.
- New sessions should restore quickly if DPD/retry settings are tuned.

## AWS Dependencies

- IAM role permission for:
  - `dynamodb:GetItem`
  - `dynamodb:UpdateItem`
  - `ec2:AssociateAddress` (if EIP move used)
- DynamoDB table with partition key `cluster_id` (String).
- Optional EIP allocated for head-end VIP behavior.
- Optional EFS file system for shared bundles/backups/log archives.
  - Mount targets must exist in the VPC.
  - Mount target security groups must allow TCP `2049` from the node security groups.
  - Use EFS for shared artifacts only, not live VPN runtime state.

## Rollback

To disable HA safely:

1. `systemctl disable --now muxingplus-ha.service`
2. keep desired node ACTIVE manually
3. remove/ignore lease table row

## Validation Checklist

- Both nodes running service and reading same `cluster_id`.
- Only one node reports `active` at any time.
- On active-node stop, standby promotes within lease timeout.
- EIP/ENI ownership follows role.
- VPN service follows role.
