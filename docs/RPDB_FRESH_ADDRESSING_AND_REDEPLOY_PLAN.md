# RPDB Fresh Addressing And Redeploy Plan

## Purpose

Stand up RPDB as a brand-new stack with a fresh private IP plan and fresh
public EIPs, without touching `<legacy-muxer3-repo>`, without touching legacy
customer state, and without onboarding customers until the empty platform is
proven clean.

This plan exists because the previous `rpdb-empty` prepared parameter set used
private IPs that are already in use by live stacks in the same VPC.

## Guardrails

- work only inside `<repo-root>` for code and
  documentation changes
- do not modify `<legacy-muxer3-repo>`
- do not reuse currently allocated private IPs
- do not reuse legacy public EIPs unless explicitly approved
- do not onboard customers during the platform rebuild
- keep the same platform shape unless explicitly changed later
- stop on failures and analyze before taking additional action

## Target End State

The project is complete when:

- RPDB exists as a separate clean stack
- RPDB uses a fresh private IP plan with no overlap against live stacks
- RPDB uses fresh public EIPs if public reachability is required
- `MUXER3` remains untouched
- the RPDB customer SoT is empty
- the RPDB allocation table is empty
- the empty platform is validated and ready for one-by-one customer onboarding

## Phase 0: Scope Lock

Goal:

- confirm this is a new RPDB stack only

Work:

- confirm no changes will be made to `<legacy-muxer3-repo>`
- confirm no customer onboarding will happen during platform rebuild
- confirm we are replacing the old `rpdb-empty` address plan
- confirm this is a fresh-stack approach, not an in-place migration

Exit gate:

- written agreement that this is a new RPDB stack only

## Phase 1: Read-Only Address Inventory

Goal:

- build a full inventory of used and available addresses in the relevant subnets

Work:

- read current subnet ranges for:
  - muxer public subnets
  - muxer transport subnets
  - NAT primary subnets
  - NAT HA/sync subnets
  - NAT core subnets
  - non-NAT primary subnets
  - non-NAT HA/sync subnets
  - non-NAT core subnets
- read all currently assigned IPs in those subnets
- read current live stack names occupying related ranges
- capture current reusable dependencies:
  - VPC
  - subnets
  - AMI
  - key pair
  - shared EFS
  - artifact bucket paths

Exit gate:

- complete used-versus-available inventory for every RPDB interface slot

## Phase 2: Build New RPDB Address Proposal

Goal:

- create a fresh address plan with no overlap

Work:

- propose new private IPs for:
  - muxer transport ENI A
  - muxer transport ENI B
  - NAT head-end A primary
  - NAT head-end A HA/sync
  - NAT head-end A core
  - NAT head-end B primary
  - NAT head-end B HA/sync
  - NAT head-end B core
  - non-NAT head-end A primary
  - non-NAT head-end A HA/sync
  - non-NAT head-end A core
  - non-NAT head-end B primary
  - non-NAT head-end B HA/sync
  - non-NAT head-end B core
- propose fresh public EIPs for:
  - muxer
  - NAT stack
  - non-NAT stack
- keep the same subnet placement and platform shape
- ensure muxer backend-underlay references match the new NAT and non-NAT
  primary IPs

Exit gate:

- one clean proposal table with zero overlaps

## Phase 3: Conflict Validation

Goal:

- prove the proposal is conflict-free before editing repo parameters

Work:

- validate every proposed private IP is unused
- validate proposed EIPs are available or allocatable
- validate no overlap with:
  - `muxer-single-prod`
  - `vpn-headend-nat-graviton-dev-us-east-1`
  - `vpn-headend-non-nat-graviton-dev-us-east-1`
  - any other relevant live stack or interface
- validate muxer underlay references point to the proposed NAT and non-NAT
  primary IPs

Failure rule:

- if any conflict is found:
  - stop
  - write a problem statement
  - generate a revised address proposal

Exit gate:

- signed-off conflict-free address plan

## Phase 4: Repo Parameter Update Plan

Goal:

- update only the RPDB repo artifacts to reflect the approved new address plan

Work:

- update the prepared muxer parameter file
- update the prepared NAT head-end parameter file
- update the prepared non-NAT head-end parameter file
- update all linked values that must move together:
  - transport ENI IPs
  - NAT primary, HA/sync, and core IPs
  - non-NAT primary, HA/sync, and core IPs
  - muxer references to NAT and non-NAT underlay IPs
  - EIP allocation IDs if they are being set at this stage

Exit gate:

- repo parameter set reflects only the approved RPDB address plan

## Phase 5: Dry-Run Validation

Goal:

- prove the parameter set is internally consistent before redeploy

Work:

- run the empty-platform deploy wrapper in plan mode
- run readiness and parameter sanity validation
- confirm there are no stale IP references
- confirm there are no unintended legacy EIP references
- confirm stack names, table names, artifact paths, and bundle targets are
  correct

Exit gate:

- dry-run plan is clean and reviewable

## Phase 6: Clean Redeploy Execution

Goal:

- create the new empty RPDB platform from the corrected parameter set

Work:

- remove any leftover `ROLLBACK_COMPLETE` RPDB muxer stack if still present
- redeploy:
  - muxer stack
  - NAT head-end stack
  - non-NAT head-end stack
  - customer SoT table
  - allocation table

Failure rule:

- if any deployment step fails:
  - stop immediately
  - capture stack events and failure details
  - do not apply fixes inline

Exit gate:

- all RPDB stacks are created successfully

## Phase 7: Empty Platform Validation

Goal:

- prove the rebuilt RPDB platform is clean and usable

Work:

- validate all RPDB nodes are running
- validate EC2 status checks pass
- validate SSM or SSH works on required nodes
- validate the customer SoT table exists and is empty
- validate the allocation table exists and is empty
- validate HA lease tables are healthy
- validate no customer artifacts are installed
- validate no customer records are present

Exit gate:

- RPDB is a clean empty platform

## Phase 8: Freeze Baseline

Goal:

- capture the new clean baseline before customer onboarding

Work:

- record:
  - stack names
  - instance IDs
  - subnet and IP matrix
  - EIPs
  - table names
  - artifact paths
  - access method
- mark this as the onboarding baseline for one-by-one customer bring-up

Exit gate:

- platform baseline is documented and stable

## Definition Of Done

This plan is complete when:

- RPDB exists as a separate clean stack
- there is no overlap with legacy private IPs
- there is no dependency on legacy public EIPs unless intentionally chosen
- `MUXER3` remains untouched
- the SoT is empty
- the allocation table is empty
- the platform is ready for one-by-one customer onboarding

## Immediate Next Step

1. Complete the read-only free-IP inventory by subnet.
2. Build the proposed replacement private IP and public EIP matrix.
3. Review that proposal before making any repo edits or retrying redeploy.

## Code Map And Restart Notes

This section is here so a new project or new thread can restart quickly without
re-discovering where the RPDB code and docs live.

### Top-Level Repo Layout

- `build`
  - generated output, rehearsal artifacts, prepared parameter sets, staged
    deployment output, and verification fixtures
  - treat this as generated state, not the long-term source of truth
- `config`
  - shared top-level config content that is not muxer-runtime-specific
- `docs`
  - project plans, onboarding docs, runbooks, deployment model notes, and
    restart references
- `infra`
  - CloudFormation templates and parameter files for muxer and VPN head-end
    platform deployment
- `muxer`
  - RPDB muxer/customer model source, schemas, request examples, runtime
    package, muxer-specific scripts, and muxer verification logic
- `ops`
  - operational assets for head-end HA and related system-level runtime support
- `scripts`
  - top-level orchestrators for platform deploy, packaging, deployment,
    backup, and customer lifecycle work

### Key Code Areas

- `scripts/platform`
  - empty-platform deploy and validation front door
  - CloudFormation deploy wrappers
  - parameter preparation
  - DynamoDB bootstrap helpers
  - head-end bootstrap verification
- `scripts/customers`
  - one-command customer deploy orchestration entry point
  - deployment environment validation
  - staged/live apply orchestration library
- `scripts/deployment`
  - lower-level apply, validate, and remove helpers for:
    - backend
    - muxer
    - VPN head-end
- `scripts/packaging`
  - customer bundle assembly
  - manifest generation
  - bundle validation
- `scripts/backup`
  - baseline and pre-change backup note helpers
- `muxer/src`
  - customer model, merge logic, artifact rendering, and framework-side source
    code for RPDB customer handling
- `muxer/runtime-package`
  - runtime code and systemd units that get installed on the muxer node
- `muxer/config`
  - schemas, deployment environments, customer requests, customer sources,
    environment defaults, and related config material
- `muxer/scripts`
  - repo verification, NAT-T watcher, rendering checks, and muxer-side test and
    validation helpers
- `ops/headend-ha-active-standby`
  - HA controller assets for VPN head-end nodes
- `infra/cfn`
  - CloudFormation templates and parameter files used by the platform deploy
    flow

### Most Important Docs

- `docs/RPDB_FRESH_ADDRESSING_AND_REDEPLOY_PLAN.md`
  - this plan for fresh addressing and clean redeploy
- `docs/RPDB_CUSTOMER_FILE_TO_DEPLOY_FULL_PROJECT_PLAN.md`
  - end-to-end phased project plan from customer file to deploy
- `docs/FRESH_EMPTY_PLATFORM_RUNBOOK.md`
  - operator-facing runbook for empty platform stand-up
- `docs/DATABASE_BOOTSTRAP.md`
  - database bootstrap expectations
- `docs/CUSTOMER_ONBOARDING_RUNBOOK.md`
  - detailed onboarding flow
- `docs/CUSTOMER_ONBOARDING_USER_GUIDE.md`
  - user-facing onboarding guide
- `docs/PRE_DEPLOY_DOUBLE_VERIFICATION.md`
  - pre-deploy validation gate
- `docs/HEADEND_CUSTOMER_ORCHESTRATION.md`
  - staged head-end customer apply/validate/remove expectations

### Current Restart Notes

- `<legacy-muxer3-repo>` is out of scope and should not be modified for RPDB work.
- The fresh address proposal has already been executed and the prepared
  parameter set under:
  - `build\empty-platform\current-prod-shape-rpdb-empty`
  now uses unused private IPs with blank `EipAllocationId` values.
- The RPDB-empty platform is deployed and currently healthy at the platform
  level:
  - `muxer-single-prod-rpdb-empty`
  - `vpn-headend-nat-graviton-dev-rpdb-empty-us-east-1`
  - `vpn-headend-non-nat-graviton-dev-rpdb-empty-us-east-1`
  are all `CREATE_COMPLETE`.
- The RPDB-empty database tables exist and are empty:
  - `muxingplus-customer-sot-rpdb-empty`
  - `muxingplus-customer-sot-rpdb-empty-allocations`
- Head-end validation passes when using the RPDB muxer as the SSH bastion
  fallback.
- SSM is still degraded on the `b` nodes, so any current validation restart
  should use the bastion-capable verification path first.
- The next correct step is not address planning anymore. The next correct step
  is customer artifact preparation and dry-run review before any live customer
  apply.

### If This Starts As A New Project

Start here, in order:

1. Read this file first.
2. Review `docs/FRESH_EMPTY_PLATFORM_RUNBOOK.md`.
3. Review `docs/RPDB_CUSTOMER_FILE_TO_DEPLOY_FULL_PROJECT_PLAN.md`.
4. Verify live AWS subnet/IP usage before changing any parameters.
5. Build a new RPDB address proposal.
6. Validate it has zero overlap with live stacks.
7. Only then update repo parameter files and retry the empty-platform deploy.
8. Once the platform is up, verify readiness with the muxer SSH bastion
   fallback if SSM is degraded.
9. Stop before customer apply until the chosen customer package is reviewed.
