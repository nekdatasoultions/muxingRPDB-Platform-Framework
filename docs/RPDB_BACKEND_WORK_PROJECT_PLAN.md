# RPDB Backend Work Project Plan

## Boundary

This plan covers RPDB backend/platform work only.

Allowed repository:

- `E:\Code1\muxingRPDB Platform Framework-main`

Not allowed in this plan without a separate approval gate:

- modifying `E:\Code1\MUXER3`
- onboarding or cutting over customers
- moving EIPs
- applying customer-specific VPN/muxer changes
- changing production DynamoDB data outside an approved backend/database step

## Goal

Prepare a production-shaped RPDB backend platform that is healthy with zero
customers deployed.

The backend platform means:

- muxer instance and runtime substrate
- NAT VPN head-end pair
- non-NAT VPN head-end pair
- customer SoT and allocation database layer
- package storage and deployment artifacts
- logging, NAT-T watcher, and monitoring plumbing
- backup and rollback baseline

This plan stops when the backend is ready for customer package deployment. It
does not deploy a customer.

Backend work must produce enough environment metadata for the one-command
customer deploy orchestrator. Operators should not manually pass node targets,
table names, artifact paths, or NAT/non-NAT head-end choices during normal
customer onboarding.

Orchestrator plan:

- `docs/RPDB_ONE_COMMAND_CUSTOMER_DEPLOY_ORCHESTRATOR_PLAN.md`

## Stage 1: Confirm Backend Targets

Define the exact backend targets before any backend deploy:

- AWS region
- muxer stack name and instance ID
- muxer private/public ENI layout
- NAT head-end stack name and active/standby instance IDs
- non-NAT head-end stack name and active/standby instance IDs
- customer SoT table name
- allocation/reservation table name
- S3 artifact bucket and prefix
- CloudWatch log groups
- SSM or SSH access path
- EIP plan: temporary rehearsal EIPs or approved real cutover EIPs

Validation:

- all target names are written into the backend deployment notes
- EIP movement is explicitly blocked unless approved as a cutover step
- no customer package is included in this stage

## Stage 2: Backup And Rollback Baseline

Create or verify a backend rollback baseline before changing the backend:

- CloudFormation stack templates and parameters
- muxer runtime config and service state
- NAT head-end runtime config and service state
- non-NAT head-end runtime config and service state
- DynamoDB table definitions and recovery settings
- S3 deployment artifact references
- IAM roles and instance profiles

Validation:

- baseline manifest exists
- baseline checksum file exists
- rollback owner is named
- validation owner is named
- backend deploy stops if any required baseline is missing

Relevant repo references:

- `docs/BACKUP_AND_ROLLBACK_BASELINE.md`
- `docs/PRE_DEPLOY_DOUBLE_VERIFICATION.md`
- `scripts/deployment/deployment_readiness_check.py`

## Stage 3: Prepare Safe Empty-Platform Parameters

Prepare a production-shaped, empty-platform parameter set that does not
accidentally move production EIPs.

Command:

```powershell
python scripts\platform\prepare_empty_platform_params.py
```

Expected output:

- `build\empty-platform\current-prod-shape-rpdb-empty`

Validation:

- imported `EipAllocationId` values are cleared in generated parameters
- muxer and head-end names are suffixed for the RPDB empty platform
- customer SoT table name is suffixed for the RPDB empty platform
- StrongSwan archive URI points to the RPDB rehearsal artifact prefix

Relevant repo reference:

- `docs/FRESH_EMPTY_PLATFORM_RUNBOOK.md`

## Stage 4: Plan Empty Backend Deploy

Generate the empty backend deploy plan before executing anything.

Command:

```powershell
python scripts\platform\deploy_empty_platform.py `
  --muxer-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.single-muxer.us-east-1.json `
  --nat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.nat.graviton-efs.us-east-1.json `
  --nonnat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json `
  --json
```

Validation:

- muxer stack action is planned
- NAT head-end stack action is planned
- non-NAT head-end stack action is planned
- customer SoT table ensure step is planned
- no customer onboarding action appears in the plan
- no production EIP movement appears unless explicitly approved

## Stage 5: Backend Software Readiness

Verify the software expected on each backend role.

Muxer must account for:

- RPDB muxer runtime package
- Python runtime and dependencies
- nftables support used by the runtime
- routing tooling: `ip`, `ip rule`, `ip route`
- systemd service wrapper for muxer runtime
- NAT-T watcher service or scheduled runner
- log source consumed by the NAT-T watcher

VPN head ends must account for:

- StrongSwan or swanctl runtime
- HA support services such as conntrackd where applicable
- filesystem mounts required by current bootstrap
- route apply tooling
- post-IPsec NAT apply tooling
- staged customer config layout under the RPDB customer path

Validation:

- muxer service can start with zero customers
- NAT head-end services can start with zero customers
- non-NAT head-end services can start with zero customers
- StrongSwan/swanctl is present on both VPN head-end stacks
- NAT-T watcher can read the configured muxer log path
- no customer-specific tunnel is required for backend health

## Stage 6: Database Bootstrap

Prepare the database layer before customer deploy.

Backend database requirements:

- customer SoT table exists
- allocation/reservation tracking table exists
- table names are environment-scoped
- point-in-time recovery or equivalent recovery stance is documented
- IAM access for deployment tooling is scoped and verified
- no customer item is written until customer deployment begins

Validation:

- database ensure/check command succeeds
- expected table names are returned
- allocation table is empty or contains only approved fixture data
- no production customer item is changed during backend preparation

Relevant repo references:

- `docs/DATABASE_BOOTSTRAP.md`
- `scripts/platform/ensure_dynamodb_tables.py`

## Stage 7: NAT-T Watcher Backend Wiring

Prepare the backend service path for automated NAT-T promotion.

Required decisions:

- watcher host: muxer node or orchestration host
- log file or CloudWatch subscription source
- state-file location
- output/package root
- customer request root
- service manager: systemd, scheduled task, or external supervisor
- retention policy for observation and package artifacts

Validation:

- watcher can process a UDP/500 then UDP/4500 fixture
- watcher writes an observation
- watcher can call `provision_customer_end_to_end.py`
- watcher output remains `live_apply: false`
- second watcher pass is idempotent

Repo-only command shape:

```powershell
python muxer\scripts\watch_nat_t_logs.py `
  --customer-request-root muxer\config\customer-requests\migrated `
  --log-file build\pre-deploy\nat-t-watcher\muxer-events.jsonl `
  --state-file build\pre-deploy\nat-t-watcher\state.json `
  --out-dir build\pre-deploy\nat-t-watcher\out `
  --package-root build\pre-deploy\nat-t-watcher\packages `
  --run-provisioning `
  --json
```

## Stage 8: Empty Backend Health Check

After backend deploy is approved and performed, validate the empty platform
before any customer package is applied.

Muxer validation:

- instance reachable by approved access path
- muxer service status is healthy
- route tables are sane with zero customer tunnels
- firewall rules are sane with zero customer tunnels
- NAT-T watcher is running or can be run on demand

VPN head-end validation:

- NAT active/standby nodes are reachable
- non-NAT active/standby nodes are reachable
- StrongSwan/swanctl service health is known
- HA/sync service health is known where used
- customer config directories exist but contain no customer deployment

Database validation:

- customer SoT table exists
- allocation table exists
- backend can read/write only after approved deployment role check

## Stage 9: Backend Completion Gate

Backend work is complete when:

- empty platform deploy plan is reviewed
- backend backups are verified
- backend software readiness is verified
- database bootstrap is verified
- NAT-T watcher backend wiring is verified
- empty muxer is healthy
- empty NAT head-end pair is healthy
- empty non-NAT head-end pair is healthy
- no customer has been deployed

Output:

- backend readiness notes
- backend backup manifest
- empty-platform deploy summary
- muxer health evidence
- NAT head-end health evidence
- non-NAT head-end health evidence
- database readiness evidence
- NAT-T watcher readiness evidence
- deployment environment file consumed by the one-command customer deploy
  orchestrator

Next plan:

- `docs/RPDB_CUSTOMER_DEPLOY_PROJECT_PLAN.md`
- `docs/RPDB_ONE_COMMAND_CUSTOMER_DEPLOY_ORCHESTRATOR_PLAN.md`
