# RPDB Customer File To Deploy Full Project Plan

## Purpose

This is the full project plan to reach the target operator workflow:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\<customer>.yaml `
  --environment rpdb-prod `
  --approve `
  --json
```

From the operator perspective:

- fill out one customer request file
- run one script
- the backend handles allocation, NAT-T promotion, target selection, package
  generation, backup gates, apply, validation, and rollback

This plan includes the node and service touch points required to get there.

## Non-Negotiable Guardrails

- work only inside `E:\Code1\muxingRPDB Platform Framework-main` for code and
  documentation changes
- do not modify `E:\Code1\MUXER3`
- do not touch legacy muxer nodes during RPDB implementation
- do not touch live nodes until the live-apply stage is explicitly approved
- do not move EIPs until a separate cutover approval is given
- deploy exactly one customer per approved customer run
- keep Customer 3 variants blocked unless explicitly approved
- use `legacy-cust0002` for strict non-NAT validation
- use `vpn-customer-stage1-15-cust-0004` for NAT-T validation
- verify each stage before moving to the next stage

## Target End State

The project is complete when an operator can run one command against one
customer file and the system does all of the following:

- validates the customer request
- allocates customer ID, fwmark, route table, RPDB priority, tunnel key,
  overlay block, interface names, and backend assignment
- defaults the customer to strict non-NAT first
- automatically promotes to NAT-T if UDP/4500 is observed after UDP/500 for
  the same customer/peer
- selects the correct RPDB muxer and VPN head end from the environment contract
- builds the DynamoDB item, muxer artifacts, VPN head-end artifacts, bundle,
  execution plan, validation plan, and rollback plan
- checks backups and owners before live apply
- writes or updates one customer SoT record
- applies only that customer's muxer artifacts
- applies only that customer's VPN head-end artifacts
- validates control plane and data plane in both initiation directions
- rolls back automatically if apply or validation fails
- writes an audit trail for the run

## Gated Phase Model

Use these phases as the control gates for the project. We do not move into the
next phase until the current phase has written evidence and the gate is marked
passed.

### Phase 0: Repo And Scope Lock

Goal:

- confirm we are working from the RPDB repo only and have a clean baseline

Allowed touch points:

- local RPDB repository only

Not allowed:

- live nodes
- AWS APIs
- DynamoDB writes
- S3 writes
- `E:\Code1\MUXER3`

Work included:

- confirm `main` is aligned with `origin/main`
- confirm repo status before changes
- confirm Customer 3 variants remain blocked
- confirm the plan and current guardrails are understood

Gate evidence:

- `git status --short --branch`
- latest commit hash
- list of files expected to change
- explicit note that no live/AWS action occurred

Exit criteria:

- repo baseline is known
- scope is locked
- Phase 1 can begin

### Phase 1: Deployment Environment Contract

Goal:

- define where the backend is allowed to deploy without requiring the operator
  to manually choose nodes, tables, or artifact paths

Allowed touch points:

- repo-only files under `muxer/config/deployment-environments`
- repo-only deployment environment schema
- repo-only validator script

Not allowed:

- live target resolution through AWS
- live node access
- live customer deploy

Work included:

- add deployment environment schema
- add example RPDB environment file
- add environment validator
- model RPDB muxer target selector
- model NAT active/standby head-end target selectors
- model non-NAT active/standby head-end target selectors
- model customer SoT table
- model allocation/reservation table
- model backup baseline root
- model artifact bucket/prefix
- model NAT-T watcher roots
- model blocked customers
- reject legacy/MUXER3 targets

Gate evidence:

- example environment validates
- Customer 3 variants are blocked by default
- legacy/MUXER3 target names fail validation
- required table, target, backup, artifact, owner, and access fields are present
- full repo verification passes

Exit criteria:

- `deploy_customer.py` can safely consume environment intent in dry-run mode

### Phase 2: Dry-Run One-Command Orchestrator

Goal:

- create the operator entry point without live writes

Allowed touch points:

- repo-only orchestrator script
- build output under `build/customer-deploy`

Not allowed:

- live apply adapters
- AWS writes
- node changes

Work included:

- add `scripts/customers/deploy_customer.py`
- accept `--customer-file`
- accept `--environment`
- accept optional `--observation`
- default to dry-run
- validate customer file
- validate environment contract
- call `muxer\scripts\provision_customer_end_to_end.py`
- write `execution-plan.json`

Gate evidence:

- Customer 2 dry-run produces a strict non-NAT execution plan
- Customer 4 with NAT-T observation produces a NAT-T execution plan
- Customer 3 is blocked
- execution plans show `live_apply: false`
- target selection is present but marked dry-run
- full repo verification passes

Exit criteria:

- one customer file can produce a reviewable dry-run execution plan

### Phase 3: Target Resolution And Backup Gate

Goal:

- make the dry-run plan deployment-aware while still preventing live writes

Allowed touch points:

- repo-only target resolver
- repo-only readiness and backup-gate logic
- build output under `build/customer-deploy`

Not allowed:

- approved live apply
- node changes
- EIP movement

Work included:

- resolve RPDB muxer target from environment
- resolve NAT active and standby head ends from environment
- resolve non-NAT active and standby head ends from environment
- select NAT or non-NAT target based on generated package
- include database and artifact targets
- check bundle manifest and checksums
- check backup baseline references
- check rollback owner and validation owner

Gate evidence:

- Customer 2 resolves to non-NAT active/standby targets
- Customer 4 NAT-T resolves to NAT active/standby targets
- missing backup data reports `blocked`
- complete backup data reports `dry_run_ready`
- no live write occurs
- full repo verification passes

Exit criteria:

- dry-run tells us exactly what would be touched and whether live apply would
  be allowed

### Phase 4: Staged Apply And Rollback

Goal:

- prove apply and rollback semantics against local/staged roots before touching
  real infrastructure

Allowed touch points:

- local staged roots under `build`
- staged DynamoDB JSON output
- staged muxer artifact root
- staged head-end artifact roots

Not allowed:

- live nodes
- AWS writes
- customer cutover

Work included:

- staged DynamoDB item writer
- staged allocation writer
- staged muxer install/apply adapter
- staged NAT head-end install/apply adapter
- staged non-NAT head-end install/apply adapter
- staged rollback adapter
- idempotency checks

Gate evidence:

- staged Customer 2 apply writes only Customer 2 artifacts
- staged Customer 4 NAT-T apply writes only Customer 4 artifacts
- staged rollback removes only the target customer
- unrelated customers remain untouched
- rerun is idempotent
- full repo verification passes

Exit criteria:

- live adapters can be implemented with proven one-customer semantics

### Phase 5: Backend Platform Readiness

Goal:

- prove the RPDB platform exists, is healthy, and has backup coverage before
  any customer live apply

Allowed touch points:

- RPDB muxer node
- RPDB NAT active/standby head-end nodes
- RPDB non-NAT active/standby head-end nodes
- DynamoDB customer SoT and allocation tables
- S3 artifact prefix
- CloudWatch or muxer log source

Not allowed:

- customer deploy
- EIP movement without separate approval
- MUXER3 modification

Work included:

- prepare empty-platform parameters
- plan empty-platform deployment
- execute empty-platform deployment after approval
- verify muxer runtime with zero customers
- verify NAT head-end pair with zero customers
- verify non-NAT head-end pair with zero customers
- verify strongSwan/swanctl on both head-end pairs
- verify database tables
- verify artifact storage
- capture backup baseline

Gate evidence:

- muxer reachable by approved access method
- NAT active/standby reachable by approved access method
- non-NAT active/standby reachable by approved access method
- strongSwan/swanctl present
- customer SoT table exists
- allocation/reservation table exists
- backup manifest and checksums exist
- rollback owner is named
- validation owner is named

Exit criteria:

- the platform is healthy with zero customers and ready for one-customer apply

### Phase 6: Approved Live Apply Adapter

Goal:

- enable the one-command script to deploy exactly one customer after approval

Allowed touch points:

- RPDB muxer active node
- selected RPDB VPN head-end active node
- selected RPDB VPN head-end standby node for staging/readiness
- DynamoDB customer SoT table
- DynamoDB allocation/reservation table
- S3 artifact/audit prefix

Not allowed:

- more than one customer per run
- Customer 3 variants
- legacy/MUXER3 targets
- EIP movement
- fleet-wide reloads unless explicitly approved

Work included:

- implement live DynamoDB put/update adapter
- implement live allocation conditional write adapter
- implement live S3 artifact/audit upload
- implement live muxer install/apply adapter
- implement live VPN head-end active install/apply adapter
- implement live VPN head-end standby stage/validate adapter
- write apply journal before each action
- require `--approve`

Gate evidence:

- dry-run remains default
- `--approve` is required for live writes
- environment must allow live apply
- apply journal contains every action
- rollback action exists for every apply action
- Customer 3 remains blocked
- full repo verification passes

Exit criteria:

- a live apply can be attempted only through the approved gated path

### Phase 7: Post-Apply Validation And Auto-Rollback

Goal:

- do not call a deployment successful until control-plane and data-plane checks
  pass in both directions

Allowed touch points:

- same customer-scoped targets touched in Phase 6
- packet capture or status commands on the selected RPDB nodes
- customer-side and core-side validation endpoints during approved cutover

Not allowed:

- unrelated customer changes
- manual node edits outside generated artifacts

Work included:

- validate muxer mark, table, RPDB priority, tunnel/interface, firewall, and
  SNAT rules
- validate VPN head-end swanctl config, SA state, route commands, and
  post-IPsec NAT when required
- validate customer/right initiated traffic
- validate core/left initiated traffic
- rollback automatically if apply or validation fails
- write final result report

Gate evidence:

- Customer 2 passes strict non-NAT validation in both directions
- Customer 4 passes NAT-T validation in both directions
- rollback test proves only the target customer is removed/restored
- final report is written

Exit criteria:

- one-customer deploy is operationally safe enough for controlled migration

### Phase 8: NAT-T Watcher Integration

Goal:

- automatic NAT-T promotion uses the same orchestrator path, not a separate
  manual workflow

Allowed touch points:

- muxer log source or CloudWatch source
- NAT-T watcher state/output root
- orchestrator dry-run or approved apply path

Not allowed:

- duplicate allocation
- bypassing approval policy
- Customer 3 variants

Work included:

- watcher detects UDP/500 then UDP/4500
- watcher writes idempotent observation
- watcher calls orchestrator with observation
- orchestrator creates NAT-T execution plan
- approved policy controls whether live promotion applies

Gate evidence:

- duplicate UDP/4500 events are idempotent
- Customer 4 NAT-T observation selects NAT head end
- live promotion remains approval-gated
- full repo verification passes

Exit criteria:

- NAT-T assignment is automatic, tracked, and deploys through the same one-file
  workflow

### Phase 9: Scale And Migration Readiness

Goal:

- confirm the flow is ready to repeat safely customer by customer

Allowed touch points:

- approved RPDB production targets
- one customer per run

Not allowed:

- bulk migration without a separate batch gate
- bypassing per-customer validation

Work included:

- document lessons from Customer 2 and Customer 4
- confirm allocation table prevents collisions
- confirm reruns are idempotent
- confirm rollback evidence is complete
- define next customer queue and change-window process

Gate evidence:

- two path proofs exist: strict non-NAT and NAT-T
- operational docs match implemented behavior
- migration queue is approved
- no known blocker remains for controlled customer-by-customer migration

Exit criteria:

- RPDB migration can proceed one customer at a time under change control

## Nodes And Services That Need To Be Touched

This section names what the deploy system is expected to touch. The exact
instance IDs must come from the deployment environment contract at runtime,
because a fresh RPDB platform can create new instances.

| Touch point | When touched | Purpose |
| --- | --- | --- |
| Operator or orchestration host | Every dry run and approved run | Runs `deploy_customer.py`, builds plans, stores execution artifacts |
| RPDB muxer active node | Approved customer deploy | Installs customer module/artifacts and applies customer-scoped RPDB, route, tunnel, firewall, SNAT, and NAT-T watcher state |
| RPDB muxer standby node, if HA muxer is introduced later | Approved platform/customer deploy | Receives compatible runtime/customer artifacts so failover does not lose customer state |
| RPDB NAT VPN head-end active node | NAT-T customer deploy only | Installs strongSwan/swanctl customer config, route commands, and post-IPsec NAT commands for NAT-T customers |
| RPDB NAT VPN head-end standby node | NAT-T customer deploy only | Stages the same customer artifacts and validates standby readiness for HA promotion |
| RPDB non-NAT VPN head-end active node | Strict non-NAT customer deploy only | Installs strongSwan/swanctl customer config and route commands for UDP/500 plus ESP/50 customers |
| RPDB non-NAT VPN head-end standby node | Strict non-NAT customer deploy only | Stages the same customer artifacts and validates standby readiness for HA promotion |
| DynamoDB customer SoT table | Approved customer deploy | Stores the canonical per-customer module/item consumed by RPDB runtime |
| DynamoDB allocation/reservation table | Dry run and approved run | Reserves customer ID, marks, tables, priorities, tunnel keys, overlays, and interface names |
| S3 artifact bucket/prefix | Backend deploy and approved customer deploy | Stores runtime bundles, customer bundles, manifests, checksums, and rollout evidence |
| CloudWatch or muxer log source | NAT-T automation | Provides UDP/500 and UDP/4500 observation input for automatic NAT-T promotion |
| Customer-side VPN device | Customer cutover only | Updates peer IP, selectors, PSK/certs, and other customer-owned VPN settings |
| Our core/cleartext-side route target | Customer cutover only when needed | Adds or validates return routes so core-initiated and customer-initiated traffic both work |

## Current Repo-Known Target Shape

The current live/dev reference from the repo is:

| Role | Name or cluster | Instance or address |
| --- | --- | --- |
| Current muxer reference | `muxer-single-prod-node` | `i-0b9501e2561b934a5`, public VPN IP `54.204.221.89`, transport `172.31.69.213` |
| Current NAT active A reference | `vpn-headend-nat-graviton-dev-headend-a` | `i-0e36a4b5425774b74`, primary `172.31.40.221`, core `172.31.55.121` |
| Current NAT standby B reference | `vpn-headend-nat-graviton-dev-headend-b` | `i-042fc7e06b4992e74`, primary `172.31.141.221`, core `172.31.88.121` |
| Current non-NAT active A reference | `vpn-headend-non-nat-graviton-dev-headend-a` | `i-03df357b7d4031524`, primary `172.31.40.220`, core `172.31.59.220` |
| Current non-NAT standby B reference | `vpn-headend-non-nat-graviton-dev-headend-b` | `i-077040652765b7928`, primary `172.31.141.220`, core `172.31.89.220` |

The RPDB-empty environment bindings currently modeled in the repo are:

| Role | Current modeled binding |
| --- | --- |
| RPDB-empty muxer public VPN IP | `13.221.247.80` |
| RPDB-empty muxer public-side private IP | `172.31.141.2` |
| RPDB-empty muxer transport IP | `172.31.127.237` |
| RPDB-empty NAT active A primary/core | `172.31.40.222` / `172.31.55.122` |
| RPDB-empty non-NAT active A primary/core | `172.31.40.223` / `172.31.59.221` |

Important interpretation:

- the current live/dev nodes above are references, not automatic RPDB targets
- the one-command deploy must reject legacy/MUXER3 targets
- the RPDB deployment environment file must become the source of truth for the
  exact RPDB node IDs, access methods, table names, and artifact roots

## Workstream 1: Backend Platform Readiness

### Stage 1.1: Confirm Backend Target Inventory

Goal:

- write down the exact RPDB backend environment that the one-command deploy is
  allowed to touch

Actions:

- define environment name, AWS region, and account
- record RPDB muxer target selector and instance ID
- record RPDB NAT head-end active and standby selectors and instance IDs
- record RPDB non-NAT head-end active and standby selectors and instance IDs
- record customer SoT table name
- record allocation/reservation table name
- record artifact bucket and prefix
- record NAT-T watcher log source and state/output roots
- record access method: SSM first, SSH only if explicitly allowed

Validation:

- inventory names only RPDB targets
- Customer 3 variants are blocked in the environment
- no MUXER3 path or legacy node is present
- EIP movement is explicitly marked blocked unless approved

### Stage 1.2: Prepare Empty Platform Parameters

Goal:

- prepare the production-shaped RPDB platform without accidentally moving live
  production EIPs

Command:

```powershell
python scripts\platform\prepare_empty_platform_params.py
```

Validation:

- generated parameter files exist under
  `build\empty-platform\current-prod-shape-rpdb-empty`
- imported `EipAllocationId` values are cleared
- stack and cluster names are suffixed for RPDB empty platform
- customer SoT table name is environment scoped
- StrongSwan archive URI points to the RPDB rehearsal artifact prefix

### Stage 1.3: Plan Empty Platform Deploy

Goal:

- prove the backend deploy plan before executing anything

Command:

```powershell
python scripts\platform\deploy_empty_platform.py `
  --muxer-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.single-muxer.us-east-1.json `
  --nat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.nat.graviton-efs.us-east-1.json `
  --nonnat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json `
  --json
```

Validation:

- plan includes one RPDB muxer deploy
- plan includes one NAT head-end pair deploy
- plan includes one non-NAT head-end pair deploy
- plan includes customer SoT table ensure
- plan does not include customer onboarding
- plan does not include EIP movement unless separately approved

### Stage 1.4: Execute Empty Platform Deploy

Goal:

- deploy the empty RPDB platform after explicit approval

Command shape:

```powershell
python scripts\platform\deploy_empty_platform.py `
  --muxer-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.single-muxer.us-east-1.json `
  --nat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.nat.graviton-efs.us-east-1.json `
  --nonnat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json `
  --execute
```

Node and service touch points:

- AWS CloudFormation
- EC2 instances created for RPDB muxer and VPN head-end pairs
- S3 artifact bucket/prefix
- DynamoDB customer SoT table
- stack-managed HA lease tables

Validation:

- muxer instance is running and reachable by approved access method
- NAT active and standby nodes are running and reachable
- non-NAT active and standby nodes are running and reachable
- strongSwan/swanctl is installed on both head-end pairs
- muxer runtime starts with zero customers
- head-end runtime starts with zero customers
- no customer tunnel exists yet

### Stage 1.5: Database And Backup Baseline

Goal:

- make database and rollback readiness a hard gate before customers

Actions:

- ensure customer SoT table exists
- ensure allocation/reservation table exists
- enable or document point-in-time recovery stance
- capture muxer baseline
- capture NAT head-end baseline
- capture non-NAT head-end baseline
- capture table definitions and artifact locations
- write rollback owner and validation owner

Validation:

- customer SoT table check passes
- allocation table check passes
- backup manifest exists
- checksum file exists
- rollback owner is named
- validation owner is named

## Workstream 2: One-Command Orchestrator Implementation

### Stage 2.1: Add Deployment Environment Contract

Goal:

- make node and service selection data-driven instead of operator-selected

Files:

- `muxer/config/schema/deployment-environment.schema.json`
- `muxer/config/deployment-environments/example-rpdb.yaml`
- `scripts/customers/validate_deployment_environment.py`

Environment contract must include:

- environment name
- AWS region and account hint
- muxer target selector
- NAT head-end active and standby target selectors
- non-NAT head-end active and standby target selectors
- customer SoT table
- allocation/reservation table
- artifact bucket and prefix
- backup baseline root
- NAT-T watcher state/output roots
- allowed customer request roots
- blocked customers
- approved access method
- live apply policy
- rollback owner
- validation owner

Validation:

- example environment validates
- Customer 3 variants are blocked by default
- legacy/MUXER3 targets are rejected
- required target, database, backup, and artifact fields are present
- validation performs no AWS calls

### Stage 2.2: Add Dry-Run Orchestrator

Goal:

- create the one script in dry-run mode first

File:

- `scripts/customers/deploy_customer.py`

Behavior:

- accepts `--customer-file`
- accepts `--environment`
- accepts optional `--observation`
- defaults to dry-run
- validates customer request
- validates environment contract
- calls `muxer\scripts\provision_customer_end_to_end.py`
- writes `build\customer-deploy\<customer>\execution-plan.json`
- does not touch live systems

Validation:

- Customer 2 dry-run creates a non-NAT execution plan
- Customer 4 plus NAT-T observation creates a NAT execution plan
- Customer 3 is blocked
- invalid environment fails clearly
- execution plan says `live_apply: false`

### Stage 2.3: Add Target Resolution

Goal:

- the operator does not choose muxer or VPN head-end targets

Rules:

- muxer target comes from environment contract
- non-NAT customer package selects non-NAT active head end
- NAT-T customer package selects NAT active head end
- standby head-end target is included for artifact staging and HA readiness
- database table comes from environment contract
- artifact root comes from environment contract

Validation:

- Customer 2 resolves to non-NAT head-end active and standby targets
- Customer 4 NAT-T resolves to NAT head-end active and standby targets
- resolved target list is written to `execution-plan.json`
- no MUXER3 or legacy target can be selected

### Stage 2.4: Add Backup And Approval Gates

Goal:

- dry-run tells us whether live apply would be allowed, and approved apply is
  impossible without backups

Checks:

- bundle manifest exists
- bundle checksums exist
- muxer backup baseline exists
- selected active head-end backup baseline exists
- selected standby head-end backup baseline exists
- customer SoT recovery stance is documented
- rollback owner is present
- validation owner is present
- environment allows live apply

Validation:

- dry-run reports `dry_run_ready` if all gates pass
- dry-run reports `blocked` if backups or owners are missing
- approved apply refuses to start if a gate fails

### Stage 2.5: Add Staged Apply Adapters

Goal:

- prove apply and rollback behavior against local/staged roots before real
  nodes

Adapters:

- staged DynamoDB customer item write output
- staged allocation/reservation item output
- staged muxer artifact install/apply
- staged NAT head-end artifact install/apply
- staged non-NAT head-end artifact install/apply
- staged rollback for one customer

Validation:

- staged Customer 2 apply writes only Customer 2 artifacts
- staged Customer 4 NAT-T apply writes only Customer 4 artifacts
- staged rollback removes only the current customer
- unrelated customers remain untouched

### Stage 2.6: Add Live Apply Adapters

Goal:

- enable approved deployment to RPDB targets only

Adapters:

- DynamoDB put/update for one customer SoT item
- DynamoDB conditional writes for allocation/reservation records
- S3 upload for customer package and audit artifacts
- muxer install/apply through approved access method
- VPN head-end active install/apply through approved access method
- VPN head-end standby artifact stage/validate through approved access method

Validation:

- `--approve` is required for any live write
- environment must allow live apply
- live target must be RPDB, not legacy
- apply journal is written before each action
- every live action has a rollback action

### Stage 2.7: Add Post-Apply Validation

Goal:

- prove the customer works before declaring success

Muxer validation:

- customer appears in muxer status
- fwmark exists
- route table exists
- RPDB priority exists
- tunnel/interface exists
- firewall rules exist
- SNAT coverage exists for all enabled protocol/source pairs
- NAT-T watcher state is sane

VPN head-end validation:

- customer swanctl config is installed
- IKE/IPsec SA state is known
- route commands are present
- post-IPsec NAT rules are present when required
- active node has expected customer config
- standby node has staged/ready customer config

Traffic validation:

- customer/right side can initiate tunnel traffic
- core/left side can initiate tunnel traffic
- non-NAT customers prove UDP/500 plus ESP/50 path
- NAT-T customers prove UDP/4500 path
- return path is validated for the exact protected subnets
- validation fails if only one direction works

### Stage 2.8: Add Rollback Automation

Goal:

- failed apply or failed validation cannot leave a half-deployed customer

Rollback order:

1. remove VPN head-end customer artifacts from active node
2. remove or mark inactive VPN head-end standby artifacts
3. remove muxer customer artifacts and runtime state
4. restore or remove customer SoT item
5. restore allocation records if the customer was newly allocated
6. write rollback result and final state

Validation:

- rollback report is written
- customer is absent or restored to prior state
- unrelated customers remain untouched
- rerunning rollback is safe

### Stage 2.9: Integrate NAT-T Watcher

Goal:

- NAT-T promotion uses the same deployment path as normal onboarding

Behavior:

- customer starts as strict non-NAT by default
- watcher sees UDP/500 from the peer
- watcher later sees UDP/4500 from the same peer
- watcher writes idempotent observation
- watcher calls orchestrator with observation
- orchestrator builds NAT-T package and selects NAT head end
- live promotion still requires environment policy and approval

Validation:

- duplicate UDP/4500 events do not duplicate allocations
- Customer 4 NAT-T package validates
- NAT-T execution plan selects NAT active and standby targets
- Customer 3 remains blocked

## Workstream 3: First Customer Deploy Flow

### Stage 3.1: Dry-Run Customer 2

Goal:

- prove one file to dry-run for strict non-NAT

Command:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\migrated\legacy-cust0002.yaml `
  --environment rpdb-prod `
  --dry-run `
  --json
```

Expected target touch plan:

- RPDB muxer active node
- RPDB non-NAT active head-end node
- RPDB non-NAT standby head-end node
- customer SoT table
- allocation/reservation table
- S3 artifact prefix

Validation:

- execution plan exists
- generated package is strict non-NAT
- UDP/500 and ESP/50 are enabled
- UDP/4500 is not enabled
- SNAT coverage includes required ESP/50 return path
- no live writes occur

### Stage 3.2: Approved Deploy Customer 2

Goal:

- deploy one strict non-NAT customer to RPDB platform

Command:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\migrated\legacy-cust0002.yaml `
  --environment rpdb-prod `
  --approve `
  --json
```

Node and service touch points:

- DynamoDB customer SoT table
- DynamoDB allocation/reservation table
- RPDB muxer active node
- RPDB non-NAT active head-end node
- RPDB non-NAT standby head-end node
- S3 artifact/audit prefix
- customer-side VPN device during cutover validation
- core/cleartext-side route target if return-route update is required

Validation:

- customer can initiate from the customer side
- core can initiate from the left/core side
- muxer sees correct customer mark/table/tunnel
- non-NAT head end sees expected strongSwan state
- packet capture confirms public encrypted path and protected cleartext path
- rollback remains available until validation owner signs off

### Stage 3.3: Dry-Run Customer 4 NAT-T

Goal:

- prove one file plus NAT-T observation to dry-run for NAT-T

Command:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\migrated\vpn-customer-stage1-15-cust-0004.yaml `
  --environment rpdb-prod `
  --observation muxer\config\customer-requests\migrated\vpn-customer-stage1-15-cust-0004-nat-t-observation.json `
  --dry-run `
  --json
```

Expected target touch plan:

- RPDB muxer active node
- RPDB NAT active head-end node
- RPDB NAT standby head-end node
- customer SoT table
- allocation/reservation table
- S3 artifact prefix

Validation:

- execution plan exists
- generated package is NAT-T
- UDP/500 and UDP/4500 are enabled
- NAT head-end target is selected automatically
- duplicate observation is idempotent
- no live writes occur

### Stage 3.4: Approved Deploy Customer 4 NAT-T

Goal:

- deploy one NAT-T customer to RPDB platform using automatic promotion path

Command:

```powershell
python scripts\customers\deploy_customer.py `
  --customer-file muxer\config\customer-requests\migrated\vpn-customer-stage1-15-cust-0004.yaml `
  --environment rpdb-prod `
  --observation <watcher-observation.json> `
  --approve `
  --json
```

Node and service touch points:

- DynamoDB customer SoT table
- DynamoDB allocation/reservation table
- RPDB muxer active node
- RPDB NAT active head-end node
- RPDB NAT standby head-end node
- S3 artifact/audit prefix
- CloudWatch or muxer log source for NAT-T observation
- customer-side VPN device during cutover validation
- core/cleartext-side route target if return-route update is required

Validation:

- customer can initiate over UDP/4500
- core can initiate and return path works
- muxer selects NAT-T behavior from observation
- NAT head end sees expected strongSwan state
- post-IPsec NAT works when configured
- rollback remains available until validation owner signs off

## Workstream 4: Operator Documentation And Handoff

### Stage 4.1: Update User-Facing Onboarding Guide

Goal:

- make the user guide match the final operator experience

Required updates:

- one customer YAML format
- dry-run command
- approved deploy command
- NAT-T automatic promotion behavior
- validation checklist
- rollback expectation
- node touch summary

Validation:

- guide does not ask operator to choose NAT or non-NAT for normal onboarding
- guide does not ask operator to choose muxer/head-end targets
- guide names the human approval gates

### Stage 4.2: Update Engineering Runbooks

Goal:

- keep the deeper engineering documents aligned with the one-command model

Required updates:

- backend work plan
- customer deploy project plan
- one-command orchestrator plan
- NAT-T provisioning docs
- fresh empty platform runbook if environment contract changes

Validation:

- docs agree on target command
- docs agree on node touch points
- docs agree Customer 3 is blocked
- docs agree no MUXER3 modification is allowed

## Master Order Of Operations

1. Phase 0: repo and scope lock.
2. Phase 1: deployment environment contract.
3. Phase 2: dry-run one-command orchestrator.
4. Phase 3: target resolution and backup gate.
5. Phase 4: staged apply and rollback.
6. Phase 5: backend platform readiness.
7. Phase 6: approved live apply adapter.
8. Phase 7: post-apply validation and auto-rollback.
9. Phase 8: NAT-T watcher integration.
10. Phase 9: scale and migration readiness.

## Stage Verification Matrix

| Stage | Verification command or evidence | Must pass before |
| --- | --- | --- |
| Repo baseline | `git status --short --branch` and repo verification | Any implementation |
| Environment schema | environment validator with example RPDB env | Dry-run orchestrator |
| Dry-run orchestrator | Customer 2 and Customer 4 execution plans | Target resolution |
| Target resolution | plan shows exact muxer/head-end/database targets | Backup gate |
| Backup gate | readiness check reports ready or blocked clearly | Staged apply |
| Staged apply | staged roots contain only target customer | Live apply |
| Staged rollback | rollback removes/restores only target customer | Live apply |
| Live apply | apply journal exists and every step has rollback | Post-apply validation |
| Validation | both initiation directions work | Signoff |
| NAT-T watcher | duplicate observations are idempotent | Automated promotion |

## Definition Of Done

This project is done when all of these are true:

- one customer file can be dry-run with one command
- one customer file can be deployed with one approved command
- normal onboarding does not require operator NAT/non-NAT selection
- NAT-T promotion is automatic when UDP/4500 is observed
- target node selection is automatic from the environment contract
- Customer 2 proves strict non-NAT path
- Customer 4 proves NAT-T path
- Customer 3 remains blocked
- muxer, head-end, DynamoDB, S3, backup, validation, and rollback artifacts are
  all captured per run
- both customer-side and core-side initiation are validated
- rollback is automatic on failure
- no MUXER3 code or node is modified by the RPDB flow

## Immediate Next Implementation Step

Start with Phase 1, which maps to Workstream 2, Stage 2.1:

1. add `muxer/config/schema/deployment-environment.schema.json`
2. add `muxer/config/deployment-environments/example-rpdb.yaml`
3. add `scripts/customers/validate_deployment_environment.py`
4. verify the example environment validates
5. verify Customer 3 variants are blocked
6. verify legacy/MUXER3 targets are rejected
7. keep live apply disabled

Phase 1 must pass before any `deploy_customer.py` implementation begins.
