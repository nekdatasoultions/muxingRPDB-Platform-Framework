# RPDB One-Command Customer Deploy Orchestrator Plan

## Goal

Reach the operator workflow:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\migrated\<customer>.yaml `
  --environment rpdb-prod `
  --approve
```

From the operator perspective:

- provide one customer file
- provide one environment name
- run one script
- the backend resolves targets, allocates resources, builds artifacts, checks
  backups, applies the customer, validates the customer, and rolls back if
  needed

The operator should not manually select:

- customer ID
- fwmark
- route table
- RPDB priority
- tunnel key
- overlay block
- GRE/VTI interface name
- muxer backend target
- NAT or non-NAT head-end target in the normal path
- DynamoDB table names
- artifact storage paths

Those details are platform-owned and must be resolved by the backend.

## Boundary

Allowed repository:

- `E:\Code1\muxingRPDB Platform Framework-main`

Normal operator flow must not:

- modify `E:\Code1\MUXER3`
- require manual node selection
- require manual NAT/non-NAT selection
- require hand-copying generated artifacts
- require hand-editing live node config
- deploy multiple customers by accident
- change Customer 3 variants without explicit approval

## Target Operator Commands

Dry run:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\migrated\legacy-cust0002.yaml `
  --environment rpdb-prod `
  --dry-run `
  --json
```

Approved customer deploy:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\migrated\legacy-cust0002.yaml `
  --environment rpdb-prod `
  --approve `
  --json
```

NAT-T promotion should use the same backend path. The NAT-T watcher should not
hand-edit a customer. It should call the orchestrator with the generated
observation/package context.

Example internal promotion shape:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\migrated\vpn-customer-stage1-15-cust-0004.yaml `
  --environment rpdb-prod `
  --observation build\nat-t-watcher\observations\vpn-customer-stage1-15-cust-0004\e24db9af662d.json `
  --approve `
  --json
```

## Required Backend Contract

The orchestrator needs an environment contract so ops does not pass target
nodes manually.

The contract should define:

- environment name
- AWS region
- muxer target selector
- NAT head-end target selector
- non-NAT head-end target selector
- customer SoT table
- allocation/reservation table
- backup baseline location
- deployment artifact bucket/prefix
- NAT-T watcher state/output roots
- approved access method: SSM, SSH, or local/staged only
- allowed customer request roots
- blocked customers
- validation command templates
- rollback command templates

Initial repo path:

- `muxer/config/deployment-environments/<environment>.yaml`

Validation:

- environment file validates before customer provisioning
- target selectors resolve to RPDB backend targets only
- MUXER3/legacy target names are rejected
- Customer 3 variants are blocked unless explicitly allowed by the environment
  file and command line

## Internal Orchestrator Phases

The one command still does several phases internally. Ops should see a summary,
not carry the work manually.

### Phase 1: Intake

Inputs:

- customer request YAML
- environment name
- optional NAT-T observation
- `--dry-run` or `--approve`

Validation:

- customer request schema passes
- customer request contains service intent only
- stack selection is omitted for normal onboarding
- dynamic NAT-T promotion defaults are active
- blocked customer list is enforced

### Phase 2: Environment Resolution

Resolve:

- active RPDB muxer target
- active RPDB non-NAT head end
- active RPDB NAT head end
- customer SoT table
- allocation table
- backup baseline
- artifact output root

Validation:

- selected targets match RPDB environment tags/names
- selected targets are reachable by the approved access method
- no MUXER3 target is selected
- NAT package resolves to NAT head end
- non-NAT package resolves to non-NAT head end

### Phase 3: Provision Package

Call the existing repo provisioning flow:

```powershell
python muxer\scripts\provision_customer_end_to_end.py <customer-file> --json
```

If an observation is supplied, include it so the package is promoted to NAT-T.

Validation:

- package status is `ready_for_review`
- `live_apply` remains `false` before the apply phase
- bundle validation is true
- double verification is true
- allocated resources are present
- allocation/reservation records are generated

### Phase 4: Build Live Execution Plan

Convert the package and environment into a concrete execution plan.

Plan contents:

- customer name
- package directory
- target muxer
- target VPN head end
- target customer SoT table
- backup baseline
- exact files to install
- exact commands to run
- exact validation commands
- exact rollback commands
- execution order
- idempotency keys

Validation:

- plan is written to `build/customer-deploy/<customer>/execution-plan.json`
- plan says whether it is dry-run or approved apply
- plan includes rollback for every live apply step
- plan includes no unrelated customer

### Phase 5: Backup Gate

Check backups before live apply.

Validation:

- muxer baseline exists
- selected VPN head-end baseline exists
- database recovery stance is known
- package manifest exists
- package checksums exist
- rollback owner is known
- validation owner is known

Dry-run behavior:

- report missing backup evidence as blocking for live apply
- still write the execution plan for review

### Phase 6: Apply Customer

This phase runs only with explicit approval.

Apply order:

1. write/update customer SoT item
2. install muxer customer artifacts
3. apply muxer customer route/rule/firewall/tunnel changes
4. install VPN head-end customer artifacts
5. apply VPN head-end swanctl/route/post-IPsec NAT changes
6. reload only customer-scoped config where possible

Validation:

- exactly one customer is changed
- customer SoT item matches reviewed package
- muxer live state matches package
- VPN head-end live state matches package
- no fleet-wide reload happens unless explicitly approved

### Phase 7: Post-Apply Validation

Run customer validation after apply.

Muxer validation:

- customer is visible in muxer status
- fwmark exists
- route table exists
- RPDB priority exists
- tunnel/interface exists
- firewall/NAT rules exist

VPN validation:

- customer connection config is installed
- IKE/IPsec SA status is known
- routes are present
- post-IPsec NAT rules are present when required

Traffic validation:

- non-NAT customer uses UDP/500 and ESP/50 path
- NAT-T customer uses UDP/4500 path
- interesting traffic reaches expected local/core subnet
- return traffic follows expected customer path

### Phase 8: Rollback

Rollback should run automatically if an apply or validation phase fails after a
live apply begins.

Rollback order:

1. remove VPN head-end customer artifacts
2. remove muxer customer artifacts
3. restore or remove customer SoT item
4. verify customer is absent or restored to previous state

Validation:

- rollback journal is written
- rollback result is written
- validation owner can see final state
- failed customer is not left half-applied

### Phase 9: Audit And Idempotency

Every run writes:

- request copy
- environment copy
- package summary
- execution plan
- apply journal
- validation report
- rollback report when used
- final result

Validation:

- rerunning the same approved customer does not allocate duplicate resources
- rerunning a completed apply reports already-applied or reconciles safely
- NAT-T promotion reuses the observation idempotency key

## Implementation Plan

### Stage 1: Environment Contract

Add:

- `muxer/config/schema/deployment-environment.schema.json`
- `muxer/config/deployment-environments/example-rpdb.yaml`
- `scripts/customers/validate_deployment_environment.py`

Validation:

- example environment validates
- blocked customer list is enforced
- target selectors are present
- database and artifact paths are present

### Stage 2: Dry-Run Orchestrator

Add:

- `scripts/customers/deploy_customer.py`

Initial behavior:

- accepts `--customer-file`
- accepts `--environment`
- defaults to `--dry-run`
- validates customer request
- validates environment
- calls `provision_customer_end_to_end.py`
- writes `execution-plan.json`
- never touches live systems

Validation:

- Customer 2 dry-run builds a non-NAT execution plan
- Customer 4 observation dry-run builds a NAT-T execution plan
- Customer 3 is blocked
- missing environment fails clearly

### Stage 3: Target Resolution

Add target resolver logic behind the orchestrator.

Resolver must:

- load environment contract
- resolve muxer target
- resolve NAT head-end target
- resolve non-NAT head-end target
- select NAT vs non-NAT head end based on generated package, not operator input
- reject legacy/MUXER3 targets

Validation:

- non-NAT package selects non-NAT head end
- NAT-T package selects NAT head end
- operator does not pass target nodes
- selected targets are written to execution plan

### Stage 4: Backup And Readiness Gate

Integrate:

- bundle manifest/checksum validation
- backup baseline validation
- rollback owner validation
- validation owner validation

Validation:

- dry-run reports live apply blocked if backups are missing
- approved run refuses to continue if backups are missing
- execution plan contains backup references

### Stage 5: Apply Adapters

Add internal adapters for:

- DynamoDB customer SoT write/update
- muxer artifact install/apply
- VPN head-end artifact install/apply

Initial implementation should support staged/local roots before real nodes.

Validation:

- staged muxer apply writes expected customer artifacts only
- staged head-end apply writes expected customer artifacts only
- one customer can be removed from staged roots
- unrelated customers remain untouched

### Stage 6: Live Apply Approval Gate

Enable approved live apply only after staged adapters pass.

Required flag:

- `--approve`

Validation:

- without `--approve`, no live write occurs
- with `--approve`, environment must allow live apply
- command refuses legacy/MUXER3 targets
- apply journal is written before each action

### Stage 7: Validation And Rollback

Add:

- post-apply validation runner
- rollback runner
- final result report

Validation:

- validation failure triggers rollback
- rollback removes only the current customer
- rollback report is written
- final status is explicit: `deployed`, `dry_run_ready`, `blocked`, or
  `rolled_back`

### Stage 8: NAT-T Watcher Integration

Update NAT-T watcher path so promotion can call the orchestrator instead of
only building a package.

Validation:

- watcher detects UDP/500 then UDP/4500
- watcher calls orchestrator with observation
- orchestrator selects NAT head end
- duplicate observations are idempotent
- live apply still requires environment approval

### Stage 9: Operator Documentation

Update:

- customer onboarding user guide
- customer deploy project plan
- backend work project plan
- NAT-T detection guide

Validation:

- operator docs show one normal command
- manual target selection appears only in internal/troubleshooting sections
- docs clearly separate dry-run, approved apply, and rollback behavior

## Definition Of Done

The target state is complete when:

- operator can submit one customer YAML
- operator can run one command for dry-run
- operator can run the same command with approval for deploy
- backend resolves muxer, VPN head end, database, backups, and artifact paths
- resources are auto-allocated and tracked
- package is built and validated
- backups are checked
- one customer is applied
- one customer is validated
- rollback is automatic on failure
- NAT-T promotion uses the same orchestration path
- Customer 3 remains blocked unless explicitly approved
- MUXER3 is never modified by this flow

## Immediate Next Step

Implement Stage 1 and Stage 2 first:

1. add the deployment environment schema and example environment
2. add the dry-run-only `scripts/customers/deploy_customer.py`
3. prove Customer 2 dry-run and Customer 4 NAT-T dry-run produce execution
   plans without live apply

Do not implement live apply until dry-run target resolution and backup gates are
validated.
