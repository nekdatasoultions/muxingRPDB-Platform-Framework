# CGNAT Customer Provisioning Integration Plan

## Purpose

This plan describes how to integrate CGNAT customer provisioning into the
existing RPDB customer provisioning and deploy flow without breaking current
non-NAT and NAT-T customers.

This plan is intentionally implementation-oriented. It focuses on:

- files that need to change
- phases and gates
- regression expectations
- rollout safety

## Desired End State

At the end of this project:

1. the shared customer provisioning flow can accept a customer with
   `transport.mode = cgnat`
2. the same deploy shape is preserved:
   - request validation
   - repo-only package generation
   - environment-based target selection
   - approved live apply
3. the flow can provision:
   - backend customer state
   - muxer activation state
   - CGNAT head-end customer state
4. legacy direct non-NAT and NAT-T customers still work unchanged

## Project Principles

### 1. Preserve Existing Behavior by Default

If `transport.mode` is absent, the flow must behave exactly like it does today.

### 2. Reuse Existing Backend Packaging

The current backend provisioning/deploy logic remains the authority for:

- allocation planning
- customer module / DDB item generation
- backend dry-run/live apply

### 3. Keep Environment-Driven Targeting

The system must continue to select muxer and head-end hosts from deployment
environment YAML, not from DynamoDB host discovery.

### 4. Introduce CGNAT Incrementally

The first integration should add one hosted CGNAT head-end target and one
customer transport family before attempting broader HA or topology expansion.

## Scope

### In Scope

- customer request/source support for CGNAT transport mode
- CGNAT-aware repo-only package generation
- CGNAT-aware target selection
- CGNAT-aware approved live apply
- combined validation and rollback planning
- full regression coverage for legacy and CGNAT paths

### Out of Scope for the First Cut

- automatic target discovery from DB
- replacing existing environment target YAML
- full HA orchestration for multiple CGNAT head ends
- redesigning the existing muxer/backend deployment pipeline from scratch

## Workstreams

### Workstream 1: Shared Model Extension

Add CGNAT transport metadata to the shared customer model while preserving
legacy behavior.

Primary changes:

- customer request schema
- rendered customer source shape
- merged customer module shape where needed

Likely files:

- `muxer/config/schema/customer-request.schema.json`
- `muxer/scripts/provision_customer_request.py`
- supporting `muxerlib` model/merge helpers as needed

Exit criteria:

- a request can declare `transport.mode = cgnat`
- legacy requests without transport changes still validate

### Workstream 2: Environment Target Extension

Add CGNAT head-end targets to environment YAML and target-selection logic.

Primary changes:

- environment YAML contract
- `_target_selection()` in the shared deploy path

Likely files:

- `muxer/config/deployment-environments/*.yaml`
- `scripts/customers/deploy_customer.py`

Exit criteria:

- CGNAT customers resolve a `cgnat_headend_active` target
- legacy customers continue to resolve only muxer + backend head ends

### Workstream 3: Repo-Only Package Integration

Build a combined package for CGNAT customers that includes:

- backend artifacts
- muxer artifacts
- CGNAT head-end artifacts

Primary changes:

- package orchestration
- readiness reporting
- bundle validation

Likely files:

- `muxer/scripts/prepare_customer_pilot.py`
- `muxer/scripts/provision_customer_end_to_end.py`
- additive helper/orchestrator under `CGNAT/` first, if needed

Exit criteria:

- a CGNAT customer generates a review package with all three surfaces
- readiness clearly reports CGNAT-specific package status

### Workstream 4: Live Apply Integration

Extend the live apply path so it can apply CGNAT customer artifacts using the
same approval model as the current flow.

Primary changes:

- apply journal
- activation bundle handling
- target-specific remote apply
- rollback plan generation

Likely files:

- `scripts/customers/live_apply_lib.py`
- `scripts/customers/deploy_customer.py`
- additive `CGNAT/` helper scripts during early rollout

Exit criteria:

- approved live apply can include a CGNAT head-end step
- rollback plan includes CGNAT removal

### Workstream 5: Validation and Regression

Build regression coverage around:

- direct non-NAT customers
- direct NAT-T customers
- CGNAT customers

Likely files:

- shared deploy/provisioning tests
- CGNAT integration tests
- staged review fixtures

Exit criteria:

- no regression in existing customer deployment flows
- CGNAT path has dry-run and staged validation coverage

## Implementation Phases

### Phase 0: Freeze the Baseline

Goal:

- establish the current deploy shape as the baseline contract

Tasks:

- document the current deploy spine
- capture current environment target rules
- capture current backend reuse assumptions

Exit criteria:

- integration design is approved
- baseline regression suite is green

### Phase 1: Add Transport Mode to the Shared Model

Goal:

- make CGNAT an expressible customer transport type

Tasks:

- extend request/schema shape
- preserve transport metadata into the source/module path
- add tests for legacy/default behavior

Exit criteria:

- `transport.mode = cgnat` is accepted
- no legacy request regressions

### Phase 2: Extend Environment Targets and Selection

Goal:

- make the shared deploy path capable of selecting CGNAT targets

Tasks:

- add `targets.cgnat.*` to environment YAML
- extend `_target_selection()`
- expose CGNAT targets in execution-plan output

Exit criteria:

- dry-run plan for a CGNAT customer reports selected CGNAT targets

### Phase 3: Build CGNAT Repo-Only Packaging

Goal:

- generate the backend, muxer, and CGNAT package surfaces together

Tasks:

- call existing backend packaging
- generate CGNAT-specific package artifacts
- merge readiness and validation reporting

Exit criteria:

- one repo-only package contains all required CGNAT surfaces
- review docs clearly identify what would be touched live

### Phase 4: Add Approved Live Apply Support

Goal:

- make approved live apply handle CGNAT customer packages

Tasks:

- add CGNAT apply phase after backend and muxer
- add CGNAT rollback phase
- record apply journal and validation results

Exit criteria:

- live apply adapter can run end to end for a CGNAT customer in staged mode

### Phase 5: Full Regression and Hardening

Goal:

- prove we did not break direct customer deployment paths

Tasks:

- run repo-only regression for legacy direct paths
- run staged/live-sim regression for CGNAT path
- verify execution-plan, readiness, and rollback outputs

Exit criteria:

- regression suite green
- no known high-severity gaps in the integrated flow

## Recommended File-by-File Start Order

1. shared schema / request model
   - `muxer/config/schema/customer-request.schema.json`
   - `muxer/scripts/provision_customer_request.py`

2. deploy target selection
   - `scripts/customers/deploy_customer.py`
   - deployment environment YAML files

3. package generation
   - `muxer/scripts/prepare_customer_pilot.py`
   - `muxer/scripts/provision_customer_end_to_end.py`
   - additive `CGNAT/` package helpers

4. live apply
   - `scripts/customers/live_apply_lib.py`

5. regression + docs
   - shared tests
   - CGNAT integration tests
   - rollout docs

## Validation Strategy

### Unit-Level

- model and schema parsing
- target-selection branch behavior
- package/readiness object construction

### Package-Level

- repo-only package generation for CGNAT
- bundle validation
- staged head-end apply simulation where supported

### Deploy-Level

- dry-run execution-plan for direct non-NAT
- dry-run execution-plan for direct NAT-T
- dry-run execution-plan for CGNAT
- staged/live-sim apply for CGNAT

### Regression Rule

Every meaningful integration slice must rerun:

- shared customer deploy tests
- CGNAT integration tests
- package validation checks

## Risks

### Risk 1: Breaking Legacy Direct Customers

Mitigation:

- preserve default behavior when `transport.mode` is absent
- keep dedicated regression for existing direct paths

### Risk 2: Overcoupling CGNAT to Backend Internals

Mitigation:

- keep backend provisioning reused as a contract boundary
- avoid inventing muxer/backend internals inside CGNAT logic

### Risk 3: Target-Selection Drift

Mitigation:

- keep environment YAML as the single host-target authority
- do not add DB-based host discovery in this project

### Risk 4: Live Apply Complexity

Mitigation:

- stage CGNAT apply after backend and muxer are already validated
- keep per-surface rollback steps explicit

## Delivery Gates

### Gate A: Model Gate

- shared request/model supports CGNAT transport
- legacy requests still pass

### Gate B: Package Gate

- repo-only CGNAT package builds successfully
- readiness is reviewable and complete

### Gate C: Apply Gate

- staged live-apply adapter supports CGNAT target set
- rollback plan is generated

### Gate D: Regression Gate

- full direct + CGNAT regression is green

## Definition of Done

This project is done when:

1. the shared deploy path accepts CGNAT customers
2. target selection includes CGNAT environment targets
3. repo-only package generation includes CGNAT artifacts
4. approved live apply can apply CGNAT customer state
5. rollback is defined
6. legacy direct customer flows still pass regression

## Recommended First Implementation Slice

The safest first code slice is:

1. add `transport.mode = cgnat`
2. extend environment target selection with `cgnat`
3. keep CGNAT repo-only package generation in `CGNAT/` as a wrapper layer
4. prove dry-run packaging and readiness first

That gets us the new integration seam with the lowest risk to existing live
customer deployment behavior.
