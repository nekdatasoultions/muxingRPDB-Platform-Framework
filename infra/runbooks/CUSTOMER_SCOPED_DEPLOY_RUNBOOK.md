# Customer-Scoped Deploy Runbook

## Goal

Deploy one customer at a time with backup-first gates.

## Preconditions

1. The target customer source validates.
2. The merged customer module and DynamoDB item build cleanly.
3. The affected live nodes have verified backups.
4. The rollout has a written rollback plan.

## Planned Workflow

### 1. Validate The Customer

- validate one source file
- verify the merged customer module
- verify the DynamoDB item

### 2. Package The Customer

- package the customer-scoped muxer artifacts
- package the customer-scoped head-end artifacts
- produce a manifest and checksums

### 3. Preflight The Environment

- confirm backup baseline for affected nodes
- confirm purpose-built pre-change backup for this rollout
- confirm target nodes and services
- confirm rollback operator and rollback steps

### 4. Apply The Customer

- apply muxer customer-scoped changes
- apply active head-end customer-scoped changes
- stage standby head-end changes

### 5. Validate

- control-plane validation
- dataplane validation
- customer-scoped counters and packet path checks

### 6. Roll Back If Needed

- stop the rollout
- restore the customer-scoped deployment artifacts
- restore node state from the pre-change backup if required
- re-run validation until the prior state is confirmed

## Notes

- This branch is still scaffolding. The concrete apply commands will be added
  after the generated artifact layout is finalized.
