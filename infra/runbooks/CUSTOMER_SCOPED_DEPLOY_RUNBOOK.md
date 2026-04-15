# Customer-Scoped Deploy Runbook

## Goal

Deploy one customer at a time with backup-first gates.

## Preconditions

1. The target customer source validates.
2. The merged customer module and DynamoDB item build cleanly.
3. The affected live nodes have verified backups.
4. The rollout has a written rollback plan.
5. The full repo-only double-verification gate has passed.

Reference:

- [PRE_DEPLOY_DOUBLE_VERIFICATION.md](/E:/Code1/muxingRPDB%20Platform%20Framework/docs/PRE_DEPLOY_DOUBLE_VERIFICATION.md)

## Planned Workflow

### 1. Validate The Customer

- validate one source file
- verify the merged customer module
- verify the DynamoDB item

### 2. Package The Customer

- export the framework-side handoff directory for one customer
- package the customer-scoped muxer artifacts
- package the customer-scoped head-end artifacts
- produce a manifest and checksums

Suggested helper:

```powershell
# On rpdb-framework-scaffold, export the customer handoff directory first.
# Then, on rpdb-deployment-model, assemble the bundle from that export.
python scripts\packaging\assemble_customer_bundle.py `
  --bundle-dir <bundle-dir> `
  --export-dir build\handoff\<customer-name>
python scripts\packaging\build_customer_bundle_manifest.py <bundle-dir>
python scripts\packaging\validate_customer_bundle.py <bundle-dir>
```

### 3. Preflight The Environment

- confirm backup baseline for affected nodes
- confirm purpose-built pre-change backup for this rollout
- confirm target nodes and services
- confirm rollback operator and rollback steps

Suggested helpers:

```powershell
python scripts\backup\verify_backup_baseline.py
python scripts\backup\create_prechange_backup_note.py `
  --customer-name <customer-name> `
  --out notes\<customer-name>\prechange.md
python scripts\deployment\create_rollout_notes.py `
  --customer-name <customer-name> `
  --bundle-dir <bundle-dir> `
  --out-dir notes\<customer-name>
python scripts\deployment\deployment_readiness_check.py `
  --customer-name <customer-name> `
  --bundle-dir <bundle-dir> `
  --prechange-backup-note notes\<customer-name>\prechange.md `
  --rollback-notes notes\<customer-name>\rollback.md
```

Or run the whole repo-only gate at once:

```powershell
python scripts\deployment\run_double_verification.py `
  --framework-repo <framework-repo> `
  --deployment-repo <deployment-repo> `
  --customer-source <framework-customer-source> `
  --environment-file <framework-environment-file> `
  --baseline-dir <baseline-dir>
```

### 4. Apply The Customer

- apply muxer customer-scoped changes
- apply active head-end customer-scoped changes
- stage standby head-end changes

Suggested head-end helpers:

```powershell
python scripts\deployment\apply_headend_customer.py `
  --bundle-dir <bundle-dir> `
  --headend-root <staged-headend-root-or-/>
python scripts\deployment\validate_headend_customer.py `
  --bundle-dir <bundle-dir> `
  --headend-root <staged-headend-root-or-/>
```

The head-end apply helper installs:

- `etc\swanctl\conf.d\rpdb-customers\<customer>.conf`
- `var\lib\rpdb-headend\customers\<customer>\...`

And it generates customer-scoped:

- route apply/remove scripts
- post-IPsec NAT apply/remove scripts
- master apply/remove wrappers

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

- The bundle-driven head-end install/apply/remove flow is now available for
  repo-only staged roots and future on-node use.
- Post-IPsec NAT still depends on the current snippet renderer. Validation will
  warn when NAT intent is enabled but the snippet contains no executable
  commands.
