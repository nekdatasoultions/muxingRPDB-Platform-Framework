# RPDB Customer Deploy Project Plan

## Boundary

This plan covers customer-by-customer deployment after the RPDB backend platform
is ready.

Allowed repository:

- `E:\Code1\muxingRPDB Platform Framework-main`

Not allowed in this plan without explicit approval:

- modifying `E:\Code1\MUXER3`
- changing customer 3 variants
- deploying more than one customer at a time
- moving EIPs
- bypassing backup, validation, or rollback gates
- hand-editing live node config outside generated RPDB artifacts

## Goal

Deploy reviewed RPDB customer packages one customer at a time.

The normal operator interface should be one command against one customer file.
The stages in this plan are the internal phases the orchestrator performs, not
manual steps an operator should carry every time.

Orchestrator plan:

- `docs/RPDB_ONE_COMMAND_CUSTOMER_DEPLOY_ORCHESTRATOR_PLAN.md`

The first planned customers are:

- `legacy-cust0002` for strict non-NAT path validation
- `vpn-customer-stage1-15-cust-0004` for NAT-T promotion path validation

Customer 3 variants remain excluded:

- `legacy-cust0003`
- `vpn-customer-stage1-15-cust-0003`

## Dependency Gate

Do not begin customer deployment until the backend work plan is complete.

Required backend evidence:

- muxer backend is healthy
- NAT VPN head-end pair is healthy
- non-NAT VPN head-end pair is healthy
- customer SoT and allocation tables are ready
- NAT-T watcher wiring is ready
- backup baseline exists
- rollback owner is named
- validation owner is named

Backend plan:

- `docs/RPDB_BACKEND_WORK_PROJECT_PLAN.md`

## Stage 1: Select One Customer

Deploy exactly one customer per change window.

Initial order:

1. `legacy-cust0002`
2. `vpn-customer-stage1-15-cust-0004`

Validation:

- customer is named in the deployment notes
- target muxer is named
- target VPN head-end stack is named
- target backend cluster is named
- change window is named
- approval owner is named
- rollback owner is named
- validation owner is named

## Stage 2: Rebuild Repo-Only Customer Package

Rebuild the customer package immediately before deployment. In the target
operator model, this is performed by the one-command orchestrator.

Internal Customer 2 command:

```powershell
python muxer\scripts\provision_customer_end_to_end.py `
  muxer\config\customer-requests\migrated\legacy-cust0002.yaml `
  --out-dir build\customer-deploy\legacy-cust0002 `
  --json
```

Internal Customer 4 NAT-T command shape:

```powershell
python muxer\scripts\watch_nat_t_logs.py `
  --customer-request muxer\config\customer-requests\migrated\vpn-customer-stage1-15-cust-0004.yaml `
  --log-file build\customer-deploy\nat-t-watcher\muxer-events.jsonl `
  --out-dir build\customer-deploy\nat-t-watcher\out `
  --state-file build\customer-deploy\nat-t-watcher\state.json `
  --package-root build\customer-deploy\nat-t-watcher\packages `
  --run-provisioning `
  --json
```

Validation:

- package status is `ready_for_review`
- `live_apply` is `false`
- bundle validation is true
- double verification is true
- customer ID, fwmark, route table, RPDB priority, tunnel key, overlay block,
  interface, and backend assignment are present
- Customer 4 NAT-T package is traceable to a UDP/4500 observation from the same
  peer

## Stage 3: Review Customer Artifacts

Review the generated package before any live apply.

Required artifacts:

- `provisioning-run.json`
- `pilot-readiness.json`
- `customer-source.yaml`
- `customer-module.json`
- `customer-ddb-item.json`
- `allocation-summary.json`
- `allocation-ddb-items.json`
- `bundle-validation.json`
- `double-verification.json`
- `bundle/`

Validation:

- peer IP is correct
- local/core selectors are correct
- remote/customer selectors are correct
- NAT intent is correct when used
- backend assignment is correct
- muxer artifacts are present
- VPN head-end artifacts are present
- DynamoDB item view is present
- rollback notes are present or ready to generate

## Stage 4: Pre-Change Backup Gate

Before live apply, verify customer-scoped and backend backup readiness.

Required backup evidence:

- muxer pre-change state
- target VPN head-end pre-change state
- customer SoT table recovery stance
- current customer item state if replacing an existing RPDB item
- generated customer bundle manifest and checksums

Validation:

- backup manifest exists
- checksum file exists
- deployment readiness check passes
- rollback owner confirms rollback commands are available
- validation owner confirms post-apply validation commands are available

Relevant repo commands:

```powershell
python scripts\deployment\deployment_readiness_check.py `
  --customer-name <customer-name> `
  --bundle-dir <customer-package>\bundle `
  --baseline-dir <backup-baseline> `
  --json
```

## Stage 5: Apply Customer Package

Apply one customer package in a controlled order. In the target operator model,
the orchestrator performs this after package, environment, backup, and approval
gates pass.

Expected apply order:

1. write or update customer SoT item
2. apply muxer customer artifacts
3. apply VPN head-end customer artifacts
4. start or reload only the affected customer services/config
5. leave unrelated customers untouched

Validation:

- only one customer is changed
- customer SoT item matches reviewed `customer-ddb-item.json`
- muxer customer route/rule/firewall/tunnel artifacts match reviewed bundle
- VPN head-end swanctl, route, and post-IPsec NAT artifacts match reviewed
  bundle
- no fleet-wide reload happens unless explicitly approved

## Stage 6: Post-Apply Validation

Validate the customer immediately after apply.

Muxer validation:

- customer appears in muxer show/status output
- expected mark exists
- expected route table exists
- expected RPDB priority exists
- expected GRE/VTI interface exists
- expected firewall/NAT rules exist
- packet capture shows expected direction and interface

VPN head-end validation:

- customer connection config is installed
- IKE/IPsec SA status is known
- route commands are present
- post-IPsec NAT rules are present when required
- packet capture shows expected encrypted and decrypted paths

End-to-end validation:

- customer-side interesting traffic reaches expected core subnet
- return traffic follows expected customer path
- customer/right side can initiate traffic and bring up or use the tunnel
- core/left side can initiate traffic and bring up or use the tunnel
- packet captures prove encrypted traffic on the public edge and cleartext only
  on the intended protected interfaces for both initiation directions
- strict non-NAT customers using UDP/500 and ESP/50 prove return-path ESP SNAT
  for the head-end public identity to the muxer public ENI private IP
- NAT-T customer uses UDP/4500 path when promoted
- non-NAT customer uses UDP/500 and ESP/50 path
- validation fails if only one side can initiate successfully

## Stage 7: Rollback Decision

If validation fails, rollback before continuing.

Rollback order:

1. stop customer-specific service/config if needed
2. remove VPN head-end customer artifacts
3. remove muxer customer artifacts
4. restore prior customer SoT item or remove new item
5. verify customer is absent or restored to previous path

Validation:

- rollback commands complete successfully
- muxer no longer carries the failed customer artifact
- VPN head-end no longer carries the failed customer artifact
- customer SoT is restored or removed as intended
- validation owner signs off after rollback

## Stage 8: Complete One Customer

A customer deployment is complete when:

- customer package was reviewed
- backups were verified
- customer package was applied once
- post-apply validation passed
- rollback was not needed, or rollback succeeded
- deployment notes are updated
- no unrelated customer changed

## Stage 9: Move To Next Customer

Only after one customer is complete:

- review lessons learned
- confirm backend health remains good
- rebuild the next customer's package
- repeat the full customer deploy plan

Initial next customer after Customer 2:

- `vpn-customer-stage1-15-cust-0004`

Do not include Customer 3 variants until they are explicitly approved.

## Current Gate

Status: waiting for backend work completion and deployment approval.

Ready inputs already exist from the repo-only pre-deploy gate:

- `build/pre-deploy/legacy-cust0002`
- `build/pre-deploy/nat-t-watcher/packages/vpn-customer-stage1-15-cust-0004`

These are review artifacts only. They are not proof that live deployment is
approved.
