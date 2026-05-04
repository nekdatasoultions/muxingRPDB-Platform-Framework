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

### 4a. Keep PKI Reference-First

The shared provisioning flow should treat CGNAT outer-tunnel certificate
material as **references first**, not as inline cert/key payloads.

That means:

- shared requests may describe certificate identity/auth references
- package/apply logic may validate those references
- shared repo-only review may generate local lab/test-bed material without
  changing the reference-first request model
- third-party or provider-backed certificate issuance remains a separate concern
  until the PKI adapter surface is explicitly extended

This keeps the integration portable across:

- existing manually managed certificates
- local/demo certificate generation
- future third-party PKI provider APIs

### 5. Keep CGNAT in the Same Repo

CGNAT should remain in the RPDB repo and should not be split into its own repo
at this stage.

Reasoning:

- the current provisioning spine already lives in this repo
- target selection already depends on shared environment YAML in this repo
- backend, muxer, and head-end apply surfaces already live in this repo
- splitting now would create schema drift, fixture drift, and versioning pain

The intended lifecycle is:

1. incubate design and transport-specific logic inside `CGNAT/`
2. promote stable shared pieces into the shared provisioning/deploy path
3. keep CGNAT-specific docs, scenario assets, and helper logic grouped under
   `CGNAT/` where appropriate

## Repo Placement Decision

### Decision

CGNAT becomes a first-class subsystem of the existing repo.

It does not become:

- a separate repo
- a sidecar deployment product with a different lifecycle

### Practical Meaning

In practice this means:

- shared request/model changes land in shared repo paths
- shared deploy/apply changes land in shared repo paths
- CGNAT-specific docs, scenario renderers, and experimental helpers may remain
  under `CGNAT/` until stabilized
- regression coverage must always include both shared and CGNAT-specific paths

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

### Workstream 2a: PKI Reference Model Extension

Extend the shared CGNAT transport model so the outer-tunnel certificate shape
is explicit enough for production integration.

Primary changes:

- separate head-end certificate references from customer-device certificate
  references
- add trust/CA reference support
- add issuance-mode/provider metadata

Likely files:

- `muxer/config/schema/customer-request.schema.json`
- `muxer/config/schema/customer-source.schema.json`
- `muxer/src/muxerlib/customer_model.py`
- `CGNAT/framework/docs/CUSTOMER_PROVISIONING_INTEGRATION_DESIGN.md`

Exit criteria:

- the shared model can distinguish:
  - CGNAT head-end identity/auth refs
  - customer-device identity/auth refs
  - trust/CA refs
- the model supports issuance modes:
  - `reference`
  - `local_generate`
  - `provider_api`
- no actual CA integration is required yet for this workstream to pass

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

This workstream is governed by:

- `CGNAT/framework/docs/CUSTOMER_PROVISIONING_REGRESSION_GATES.md`

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

### Phase 2a: Extend the PKI Reference Shape

Goal:

- make certificate ownership and trust explicit in the shared CGNAT model

Tasks:

- split coarse outer cert/auth metadata into explicit head-end/customer/trust
  references
- add issuance-mode metadata
- preserve backward compatibility for the current simpler `outer_identity_ref`
  and `outer_auth_ref` shape during migration

Exit criteria:

- the shared model can represent unique head-end and customer cert references
- the shared model can describe whether PKI material is:
  - referenced
  - locally generated
  - provider-issued
- legacy CGNAT examples still validate or have a clearly documented migration

Implementation note:

- the initial slice is now implemented for:
  - `reference`
  - `local_generate`
- `provider_api` remains a planned adapter and is not yet executable

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
- regression/release gates approved for the next deployment stage

### Phase 6: PKI Provider Integration

Goal:

- add optional issuance/provider integration on top of the stabilized
  reference model

Tasks:

- define provider adapter contract
- implement one provider path only after the reference model is stable
- keep production-safe separation between cert references and private key
  material handling

Exit criteria:

- one supported provider mode can resolve or issue outer-tunnel certificate
  material through a controlled adapter
- `reference` mode still works unchanged
- regression gates remain green for both legacy and CGNAT flows

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

Before any real deployment attempt, the release gates in:

- `CGNAT/framework/docs/CUSTOMER_PROVISIONING_REGRESSION_GATES.md`

must be explicitly reviewed and passed.

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

### Risk 5: PKI Coupling Too Early

Mitigation:

- stabilize the reference model before adding provider-specific issuance
- keep cert/key payloads out of shared customer requests
- prefer adapter boundaries over provider-specific logic spread across the
  deploy spine

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

### Gate E: Real Deployment Gate

- all regression/release gates are green
- environment target YAML is approved
- repo-only readiness package is approved
- staged/simulated apply is approved
- no unresolved high-severity blockers remain

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

## Regression Discipline

The regression discipline used during the first CGNAT rendition should remain
the standard for this integration:

1. stop on any meaningful failure
2. fix the issue before moving to the next phase
3. rerun the affected regression layer
4. rerun the broader shared regression before advancing gates

Progression to real deployment is gated, not assumed.
