# RPDB Next Steps Reference Plan

## Purpose

This is the resume point for the RPDB work after we pause to look at something
else.

The immediate direction is to turn the RPDB customer flow into:

```text
fill out one customer file
run one script
backend handles the rest
```

That includes automatic NAT-T assignment. Customers start on the non-NAT path.
If the muxer observes UDP/4500 from that same customer, RPDB promotes the
customer to the NAT-T path automatically.

## Current State

Already complete:

- Customer request files can omit NAT/non-NAT selection.
- Normal customer requests default to strict non-NAT first.
- Platform-owned resources are allocated and tracked automatically.
- NAT-T watcher can detect UDP/500 followed by UDP/4500.
- NAT-T watcher can create a promotion observation.
- NAT-T promotion can build a NAT package.
- Customer 2 non-NAT repo-only package validates.
- Customer 4 NAT-T repo-only package validates.
- Full repo verification passes.
- Backend and customer deploy plans are split.
- One-command customer deploy orchestrator plan exists.

Important guardrails:

- stay inside `E:\Code1\muxingRPDB Platform Framework-main`
- do not modify `E:\Code1\MUXER3`
- do not touch Customer 3 variants
- do not touch live nodes without explicit approval
- do not move EIPs without explicit approval

## Next Workstream: One-Command Orchestrator

Primary reference:

- `docs/RPDB_ONE_COMMAND_CUSTOMER_DEPLOY_ORCHESTRATOR_PLAN.md`
- `docs/RPDB_SNAT_AND_ORCHESTRATOR_PROJECT_PLAN.md`

Target operator command:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\migrated\<customer>.yaml `
  --environment rpdb-prod `
  --approve `
  --json
```

The first implementation should be dry-run only.

## Step 1: Add Environment Contract

Add the environment file model that tells the backend where things live.

Files to add:

- `muxer/config/schema/deployment-environment.schema.json`
- `muxer/config/deployment-environments/example-rpdb.yaml`
- `scripts/customers/validate_deployment_environment.py`

The environment file should include:

- environment name
- AWS region
- muxer target selector
- NAT head-end target selector
- non-NAT head-end target selector
- customer SoT table
- allocation table
- backup baseline location
- artifact bucket/prefix
- NAT-T watcher output/state roots
- allowed customer request roots
- blocked customers
- validation owner
- rollback owner

Validation:

- example environment validates
- Customer 3 variants are blocked by default
- MUXER3/legacy targets are rejected
- required database and artifact fields are present

## Step 2: Add Dry-Run Customer Orchestrator

Add:

- `scripts/customers/deploy_customer.py`

Initial behavior:

- accepts `--customer-file`
- accepts `--environment`
- accepts optional `--observation`
- defaults to dry-run
- validates customer file
- validates environment file
- calls `muxer/scripts/provision_customer_end_to_end.py`
- writes `build/customer-deploy/<customer>/execution-plan.json`
- does not touch live systems

Validation:

- Customer 2 dry-run produces a non-NAT execution plan.
- Customer 4 with NAT-T observation produces a NAT execution plan.
- Customer 3 is blocked.
- Missing or invalid environment fails clearly.
- No live apply occurs.

## Step 3: Add Target Resolution

Teach the orchestrator to choose targets from the generated package and
environment file.

Rules:

- non-NAT package selects the non-NAT head end
- NAT-T package selects the NAT head end
- muxer target comes from the environment contract
- database table comes from the environment contract
- operator does not manually select targets

Validation:

- Customer 2 resolves to non-NAT head end.
- Customer 4 NAT-T resolves to NAT head end.
- target choices appear in `execution-plan.json`
- legacy/MUXER3 targets are rejected

## Step 3A: Add Head-End Egress Source SNAT Contract

Close the NAT-T version of the left/core-initiation failure found on the old
stack. RPDB must not assume that encrypted return traffic always leaves the VPN
head end sourced from only the backend underlay IP.

Required behavior:

- model every valid head-end encrypted egress source for a customer
- always include the selected backend underlay IP
- allow the environment or bound package to add public identity, loopback, or
  other source aliases when the head end can emit traffic from them
- generate muxer public-side SNAT for every valid egress source
- apply that SNAT to UDP/500, UDP/4500, and ESP/50 when each protocol is
  enabled for the customer
- block live apply if a NAT-T customer lacks UDP/4500 SNAT coverage for all
  valid head-end egress sources
- block live apply if a strict non-NAT customer lacks ESP/50 SNAT coverage for
  all valid head-end egress sources

Implementation targets:

- customer/environment model: add a head-end egress source list or equivalent
  bound artifact field
- artifact renderer: include the egress source list in muxer firewall intent
- runtime muxer apply: render SNAT rules for each source/protocol pair
- validators: fail when protocol coverage is incomplete
- deploy orchestrator: include the coverage check in dry-run and pre-live gates

Validation:

- Customer 2 non-NAT dry-run proves UDP/500 and ESP/50 SNAT coverage
- Customer 4 NAT-T dry-run proves UDP/500 and UDP/4500 SNAT coverage
- tests include a NAT-T head end with a source alias different from backend
  underlay IP
- execution plan shows the exact SNAT sources and protocols
- bidirectional initiation validation remains blocked until both sides work

## Step 4: Add Backup Gate To Dry-Run

Dry-run should check whether the live apply would be allowed.

Add checks for:

- bundle manifest
- bundle checksums
- backend backup baseline
- muxer backup baseline
- selected VPN head-end backup baseline
- rollback owner
- validation owner

Validation:

- dry-run reports `dry_run_ready` if all gates pass
- dry-run reports `blocked` if backups or owners are missing
- approved/live mode remains disabled for now

## Step 5: Add Staged Apply Adapters

Before live nodes, support staged/local roots only.

Adapters:

- staged DynamoDB item write output
- staged muxer artifact install/apply
- staged VPN head-end artifact install/apply
- staged remove/rollback for one customer

Validation:

- staged Customer 2 apply writes only Customer 2 artifacts
- staged Customer 4 NAT-T apply writes only Customer 4 artifacts
- staged rollback removes only the current customer
- unrelated customers remain untouched

## Step 6: Integrate NAT-T Watcher With Orchestrator

The NAT-T watcher should call the orchestrator path, not a separate manual flow.

Desired behavior:

- watcher sees UDP/500 then UDP/4500
- watcher writes idempotent observation
- watcher invokes customer orchestrator with that observation
- orchestrator generates the NAT-T execution plan
- live apply still requires approval/environment policy

Validation:

- duplicate UDP/4500 events do not duplicate allocation
- Customer 4 NAT-T still validates
- NAT-T execution plan selects NAT head end

## Step 7: Only Then Plan Live Apply

Do not implement live apply until:

- dry-run orchestrator works
- target resolution works
- backup gate works
- staged apply works
- staged rollback works
- NAT-T watcher integration works

Live apply must require:

- explicit `--approve`
- environment allows live apply
- backups pass
- target nodes are RPDB nodes
- rollback commands exist

## Definition Of Done For This Next Block

This next block is complete when:

- one dry-run command works for Customer 2
- one dry-run command works for Customer 4 NAT-T
- Customer 3 remains blocked
- target resolution is automatic
- head-end egress source SNAT coverage is generated and validated
- operator does not choose NAT/non-NAT
- operator does not choose muxer/head-end targets
- execution plans are written and reviewable
- full repo verification passes
- changes are committed and pushed

## Resume Command Ideas

Customer 2 dry-run target:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\migrated\legacy-cust0002.yaml `
  --environment example-rpdb `
  --dry-run `
  --json
```

Customer 4 NAT-T dry-run target:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\migrated\vpn-customer-stage1-15-cust-0004.yaml `
  --environment example-rpdb `
  --observation muxer\config\customer-requests\migrated\vpn-customer-stage1-15-cust-0004-nat-t-observation.json `
  --dry-run `
  --json
```
