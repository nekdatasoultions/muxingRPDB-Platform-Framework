# Infrastructure

This directory holds the deployment-facing assets for the RPDB platform model.

The goal on this branch is to make deployment workflow explicit before any live
node is pointed at the new framework.

## Planned Layout

```text
infra/
  backups/
  cfn/
  packaging/
  runbooks/
```

## Intent

- `backups/`
  - inventory and expectations for backup-first deployment gates
- `cfn/`
  - imported current-state CloudFormation templates and parameter files
- `packaging/`
  - bundle layout and release artifact expectations
- `runbooks/`
  - customer-scoped deployment and rollback steps

## Guardrails

- No live deploys from this repo without verified backups.
- Customer deploy/apply should be customer-scoped by default.
- Rollback expectations must be documented before rollout logic is added.

Reference:

- [RPDB documentation index](../docs/README.md)
