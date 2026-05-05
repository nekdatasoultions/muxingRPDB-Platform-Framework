# CGNAT Customer Provisioning Regression Gates

## Purpose

This document defines the regression and release gates that must be passed
before the CGNAT customer provisioning integration is allowed to move toward a
real deployment.

The goal is to preserve the same testing discipline used during the first
CGNAT rendition:

- build a slice
- stop on issues
- fix the issue
- rerun regression
- only then move forward

## Core Rule

No real deployment attempt should happen until all required gates below are
green for the current implementation slice.

## Regression Layers

### Layer 1: CGNAT-Local Regression

Purpose:

- prove that the CGNAT framework, renderers, and transport-specific helpers
  still behave correctly

Examples:

- CGNAT unit tests
- bundle/render validation
- Scenario 1 package/build tests

Current command:

```powershell
python E:\Code1\muxingRPDB Platform Framework-main\CGNAT\tests\run_tests.py
```

### Layer 2: Shared Provisioning Regression

Purpose:

- prove that shared customer provisioning behavior still works for legacy
  direct customers

This must cover, at minimum, the shared flow around:

- `muxer/scripts/provision_customer_request.py`
- `muxer/scripts/prepare_customer_pilot.py`
- `muxer/scripts/provision_customer_end_to_end.py`
- `scripts/customers/deploy_customer.py`
- `scripts/customers/live_apply_lib.py`

Expected coverage:

- direct non-NAT customer path
- direct NAT-T customer path
- shared request/model validation
- package and readiness generation

### Layer 3: Staged / Simulated Deploy Regression

Purpose:

- prove the end-to-end deploy shape without touching live infrastructure

This should cover:

- staged target selection
- staged backend apply
- staged muxer apply
- staged head-end apply
- staged CGNAT head-end apply once integrated
- both CGNAT outer topologies once modeled:
  - `per_customer_outer`
  - `shared_isp_gateway`

### Layer 4: Review Artifact Regression

Purpose:

- prove that readiness, execution-plan, apply-order, validation, and rollback
  outputs remain internally consistent

This should cover:

- package manifest
- readiness report
- execution plan
- target selection summary
- rollback plan
- topology-specific package shape
- backend feature parity expectations for inner termination

## Required Gates

### Gate 0: Baseline Freeze

Before starting a new integration phase:

- current direct customer regression is green
- current CGNAT-local regression is green
- current deployment environment examples remain valid

Pass criteria:

- we have a known-good baseline before changing shared code

### Gate 1: Shared Model Gate

Scope:

- request schema
- rendered customer source/module shape
- legacy default behavior

Must pass:

- direct non-NAT regression
- direct NAT-T regression
- CGNAT-local regression

Pass criteria:

- adding `transport.mode = cgnat` does not break legacy requests

### Gate 2: Target Selection Gate

Scope:

- environment YAML
- `_target_selection()`
- execution-plan reporting

Must pass:

- environment validation
- shared provisioning regression
- staged target-selection fixtures

Pass criteria:

- direct customers still select only their current targets
- CGNAT customers select backend targets plus CGNAT targets

### Gate 3: Repo-Only Package Gate

Scope:

- repo-only package generation
- readiness reporting
- bundle validation

Must pass:

- direct non-NAT package generation
- direct NAT-T package generation
- CGNAT package generation
- review artifact regression

Pass criteria:

- one CGNAT package contains backend, muxer, and CGNAT surfaces
- readiness is reviewable and complete
- topology-specific surfaces are explicit and internally consistent

### Gate 4: Staged Apply Gate

Scope:

- staged/simulated apply path
- rollback path

Must pass:

- staged direct non-NAT deploy
- staged direct NAT-T deploy
- staged CGNAT deploy
- rollback artifact validation

Pass criteria:

- the integrated apply order works in staged mode
- the rollback plan is complete and reviewable
- inner termination still preserves the expected backend service capabilities
  for the customer, including NAT-related behavior

### Gate 5: Full Regression Gate

Scope:

- entire integrated system

Must pass:

- CGNAT-local regression
- shared provisioning regression
- staged/simulated deploy regression
- review artifact regression

Pass criteria:

- all regression layers are green from one clean code state

### Gate 6: Real Deployment Readiness Gate

Scope:

- final pre-deploy approval

Must pass:

- all prior gates
- environment target YAML review
- CGNAT package review
- rollback review
- validation plan review
- no unresolved high-severity blockers

Pass criteria:

- explicit Go / No-Go approval for real deployment

## Stop Conditions

Progress must stop and return to fix/test mode if:

- a legacy direct-customer regression fails
- target selection becomes ambiguous
- staged apply no longer matches declared execution order
- rollback artifacts become incomplete
- CGNAT package generation requires hidden manual assumptions

## Required Review Artifacts Before Real Deployment

Before real deployment, the following must exist and be reviewed:

- shared integration design
- integration implementation plan
- readiness report
- execution plan
- target-selection summary
- validation plan
- rollback plan

Recommended docs:

- `CGNAT/framework/docs/CUSTOMER_PROVISIONING_INTEGRATION_DESIGN.md`
- `CGNAT/framework/docs/CUSTOMER_PROVISIONING_INTEGRATION_PLAN.md`
- `CGNAT/framework/docs/CGNAT_TOPOLOGY_EXPANSION_EXECUTION_PLAN.md`
- `CGNAT/framework/docs/VALIDATION_PLAN.md`

## Regression Expectations by Phase

### Early Phases

For phases that only touch model/schema/planning:

- CGNAT-local regression
- shared provisioning regression

### Middle Phases

For phases that touch package generation or target selection:

- CGNAT-local regression
- shared provisioning regression
- review artifact regression

### Late Phases

For phases that touch live apply orchestration:

- CGNAT-local regression
- shared provisioning regression
- staged/simulated deploy regression
- review artifact regression

## Recommended Execution Pattern

For each implementation slice:

1. make the smallest coherent code change
2. run the narrowest relevant regression first
3. fix any failure immediately
4. rerun the narrow regression
5. rerun the broader required gate regressions
6. update docs and handoff notes
7. only then advance to the next gate

## Definition of Ready for Real Deployment

The CGNAT customer provisioning integration is ready for a real deployment
attempt only when:

1. the repo-placement decision remains unchanged
2. the shared deploy spine still works for legacy customers
3. CGNAT customers are supported as a first-class transport family
4. all regression gates are green
5. the pre-deployment review artifacts are complete
6. the Go / No-Go decision is explicitly passed
