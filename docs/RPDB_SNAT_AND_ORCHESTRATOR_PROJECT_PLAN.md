# RPDB SNAT And Orchestrator Project Plan

## Purpose

This plan defines the repo-only order of operations for the next RPDB work
block. The goal is to make customer onboarding work like this:

```text
fill out one customer file
run one script
backend handles allocation, NAT-T promotion, target selection, validation, and
artifact generation
```

This plan does not deploy to live nodes, does not call AWS, and does not move
EIPs.

## Guardrails

- work only inside `<repo-root>`
- do not modify `<legacy-muxer3-repo>`
- do not touch live muxer or VPN head-end nodes
- do not call AWS APIs
- do not write DynamoDB
- do not move EIPs
- keep Customer 3 variants blocked
- use Customer 2 for non-NAT validation
- use Customer 4 for NAT-T validation
- verify each stage before moving to the next stage

## Order Of Operations

## Stage 0: Repo Safety Baseline

Goal:

- confirm the working repo state before implementation
- preserve existing user/Codex changes
- identify the exact files changed by each stage

Actions:

- run `git status --short`
- review existing changed files
- avoid touching unrelated files

Validation:

- only expected RPDB repo files are changed
- no files outside the repo are changed
- no live/AWS commands are run

Exit criteria:

- repo state is understood and safe to continue

## Stage 1: Model Head-End Egress Sources

Goal:

- represent every valid encrypted egress source a VPN head end may use for a
  customer

Actions:

- add a model field for head-end encrypted egress sources, or an equivalent
  bound artifact field
- always include the selected backend underlay IP
- allow environment binding to add source aliases such as public identity,
  loopback, or other local source IPs
- document that this is platform/environment-owned, not customer-request-owned

Validation:

- schema validation accepts the new field
- Customer 2 non-NAT model includes backend underlay IP
- Customer 4 NAT-T model includes backend underlay IP
- a fixture can include an additional NAT-T source alias
- Customer 3 remains blocked

Exit criteria:

- the model can express all encrypted egress sources that need muxer SNAT

## Stage 2: Render SNAT Coverage Into Artifacts

Goal:

- make generated muxer artifacts show the exact SNAT coverage needed before any
  live apply

Actions:

- add egress source coverage to muxer firewall intent
- render SNAT commands for each source/protocol pair
- include UDP/500 when enabled
- include UDP/4500 when enabled
- include ESP/50 when enabled
- keep protocol behavior tied to the resolved customer module

Validation:

- Customer 2 non-NAT artifacts show UDP/500 and ESP/50 SNAT coverage
- Customer 4 NAT-T artifacts show UDP/500 and UDP/4500 SNAT coverage
- a NAT-T fixture with an additional source alias renders an extra UDP/4500
  SNAT rule
- rendered artifacts contain no unresolved placeholders

Exit criteria:

- generated artifacts clearly prove which sources and protocols will be SNATed

## Stage 3: Update Runtime Muxer Apply Logic

Goal:

- make the runtime muxer apply path enforce the same SNAT behavior as the
  reviewed artifacts

Actions:

- update customer-scoped muxer apply logic to iterate over all head-end egress
  sources
- generate public-side SNAT for UDP/500, UDP/4500, and ESP/50 when enabled
- keep the backend underlay behavior as the default source
- avoid fleet-wide reload assumptions

Validation:

- runtime scripts compile
- generated rule plans include every expected source/protocol pair
- strict non-NAT Customer 2 still uses UDP/500 and ESP/50
- NAT-T Customer 4 still uses UDP/500 and UDP/4500

Exit criteria:

- runtime apply behavior matches the reviewed artifact model

## Stage 4: Add Validators And Gates

Goal:

- block incomplete SNAT coverage before deployment planning advances

Actions:

- add validator checks for egress source SNAT coverage
- fail NAT-T customers missing UDP/4500 coverage for any valid egress source
- fail strict non-NAT customers missing ESP/50 coverage for any valid egress
  source
- add these checks to double verification and customer deploy readiness

Validation:

- valid Customer 2 non-NAT package passes
- valid Customer 4 NAT-T package passes
- synthetic NAT-T alias-missing package fails clearly
- synthetic non-NAT ESP-missing package fails clearly
- error output names the missing source and protocol

Exit criteria:

- incomplete return-path SNAT coverage cannot pass repo-only validation

## Stage 5: Add Deployment Environment Contract

Goal:

- define where the one-command orchestrator is allowed to operate without
  hardcoding live details into customer files

Actions:

- add deployment environment schema
- add example RPDB deployment environment
- add deployment environment validator
- include muxer target selector
- include NAT and non-NAT head-end target selectors
- include customer SoT and allocation table names as data only
- include backup baseline locations as data only
- include allowed request roots and blocked customers

Validation:

- example environment validates
- Customer 3 variants are blocked by default
- legacy/MUXER3 targets are rejected
- no AWS calls are made

Exit criteria:

- orchestrator can load environment intent without touching live systems

## Stage 6: Add Dry-Run Customer Orchestrator

Goal:

- create the one-script operator entry point in dry-run mode

Actions:

- add `scripts\customers\deploy_customer.py`
- accept `--customer-file`
- accept `--environment`
- accept optional `--observation`
- default to dry-run
- call the existing provisioning pipeline
- write `build\customer-deploy\<customer>\execution-plan.json`
- do not apply anything live

Validation:

- Customer 2 dry-run produces a non-NAT execution plan
- Customer 4 with NAT-T observation produces a NAT execution plan
- Customer 3 is blocked
- invalid environment fails clearly
- execution plan shows no live apply

Exit criteria:

- one dry-run command can prepare a customer execution plan

## Stage 7: Add Automatic Target Resolution

Goal:

- remove manual target selection from the operator workflow

Actions:

- non-NAT package selects the non-NAT head end
- NAT-T package selects the NAT head end
- muxer target comes from the environment contract
- database target comes from the environment contract
- resolved targets are written to `execution-plan.json`

Validation:

- Customer 2 resolves to the non-NAT head end
- Customer 4 NAT-T resolves to the NAT head end
- legacy/MUXER3 targets are rejected
- operator does not manually choose NAT or non-NAT

Exit criteria:

- target selection is deterministic and reviewable

## Stage 8: Add Backup And Approval Gates

Goal:

- ensure dry-run can report whether a live apply would be allowed later

Actions:

- check bundle manifest
- check bundle checksums
- check backup baseline references
- check rollback owner
- check validation owner
- keep approved/live mode disabled for this block

Validation:

- dry-run reports `dry_run_ready` when gates pass
- dry-run reports `blocked` when required backup or owner data is missing
- no live apply occurs

Exit criteria:

- dry-run can distinguish ready from blocked without touching live systems

## Stage 9: Add Staged Apply And Rollback Adapters

Goal:

- test apply and rollback behavior against local/staged roots only

Actions:

- add staged DynamoDB write output
- add staged muxer artifact install/apply
- add staged VPN head-end artifact install/apply
- add staged customer-scoped remove/rollback
- keep all outputs under `build`

Validation:

- staged Customer 2 apply writes only Customer 2 artifacts
- staged Customer 4 NAT-T apply writes only Customer 4 artifacts
- staged rollback removes only the current customer
- unrelated customers remain untouched

Exit criteria:

- apply and rollback behavior is proven locally before any live-node design

## Stage 10: Integrate NAT-T Watcher With Orchestrator

Goal:

- make NAT-T promotion flow through the same one-command path

Actions:

- watcher observes UDP/500 followed by UDP/4500
- watcher writes an idempotent observation
- watcher invokes or prepares orchestrator input with that observation
- orchestrator builds the NAT-T execution plan
- live apply remains disabled

Validation:

- duplicate UDP/4500 events do not duplicate allocation
- Customer 4 NAT-T promotion still validates
- NAT-T execution plan selects NAT head end
- NAT-T execution plan includes UDP/4500 SNAT coverage for every egress source

Exit criteria:

- automatic NAT-T assignment is integrated into the customer deploy workflow

## Stage 11: Final Repo-Only Verification

Goal:

- prove the full repo-only flow before any live deployment planning resumes

Actions:

- run unit/script compile checks
- run schema validations
- run Customer 2 non-NAT dry-run
- run Customer 4 NAT-T dry-run
- run staged apply and rollback for both customers
- run full repo verification

Validation:

- Customer 2 passes non-NAT path
- Customer 4 passes NAT-T path
- Customer 3 remains blocked
- SNAT coverage is complete
- bidirectional initiation validation requirements are present
- no live/AWS command was run

Exit criteria:

- repo-only implementation is ready for human review

## Stage 12: Stop Gate Before Live Work

Goal:

- pause before any live-node, AWS, DynamoDB, or EIP action

Required review:

- execution plans
- generated customer artifacts
- SNAT coverage report
- target resolution report
- backup gate report
- staged apply and rollback results
- rollback expectations
- validation commands for both initiation directions

Exit criteria:

- human approval is required before live deployment planning can continue

## Definition Of Done

This project block is complete when:

- Customer 2 dry-run works end to end as non-NAT
- Customer 4 dry-run works end to end as NAT-T
- Customer 3 remains blocked
- head-end egress source SNAT coverage is modeled
- SNAT coverage is generated for UDP/500, UDP/4500, and ESP/50 when enabled
- validators block incomplete SNAT coverage
- operator does not choose NAT/non-NAT manually
- operator does not choose muxer/head-end targets manually
- staged apply and rollback work locally
- NAT-T watcher integrates with the orchestrator path
- full repo verification passes
- no live nodes, AWS APIs, DynamoDB writes, or EIP moves occurred

