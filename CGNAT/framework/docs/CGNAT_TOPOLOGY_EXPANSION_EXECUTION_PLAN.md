# CGNAT Topology Expansion Execution Plan

## Purpose

This plan describes how we will extend CGNAT provisioning to support both
supported outer-tunnel ownership models while preserving the full inner VPN
service feature set.

The goal is to execute this work with the same discipline used during the
earlier CGNAT rollout:

1. make the smallest coherent slice
2. run the narrowest relevant tests
3. stop on issues
4. fix the issue
5. rerun the slice tests
6. rerun the broader regression gates
7. only then advance

No real-node changes should happen until the pre-live gates in this plan are
green.

## Objective

Deliver one CGNAT provisioning system that supports:

1. `per_customer_outer`
   - customer device owns the outer certificate-auth tunnel
   - customer device also owns the inner PSK tunnel

2. `shared_isp_gateway`
   - ISP CGNAT gateway owns the shared outer certificate-auth tunnel
   - customer device owns the inner PSK tunnel only

Both topologies must target the same hosted CGNAT head-end platform.

## Service Requirement

The inner tunnel must terminate into a normal backend VPN service model.

That means the inner service must retain the same functional surface as a
regular direct customer, including:

- non-NAT service behavior
- NAT-T service behavior
- inside NAT
- outside NAT
- normal route-via / backend handoff behavior
- normal selector and backend policy behavior

CGNAT changes transport and ownership, not the backend VPN feature set.

## Execution Boundary

This plan ends at the point where we are ready to touch real nodes.

That means this plan must produce:

- implementation slices
- regression gates
- staged end-to-end proof
- review artifacts
- rollback artifacts
- explicit Go / No-Go criteria

It does **not** authorize live changes by itself.

## Current Baseline Assumptions

Before starting this plan:

- current direct non-NAT provisioning path is green
- current direct NAT-T provisioning path is green
- current CGNAT integration baseline is green
- current Customer 1 / Customer 2 operational findings are preserved as
  reference context, not as the implementation model

## Workstreams

### Workstream A: Shared Model and Topology

Add explicit topology modeling to the shared CGNAT request/source/module path.

Deliverables:

- `transport.mode = cgnat`
- `outer_topology = per_customer_outer | shared_isp_gateway`
- optional `outer_gateway_ref`
- preserved backend family and NAT controls

Pass criteria:

- requests validate for both topologies
- legacy direct customers still validate unchanged

### Workstream B: Package and Review Surfaces

Extend repo-only packaging and readiness reporting so both CGNAT topologies
produce clear, reviewable artifacts.

Deliverables:

- backend review surface
- muxer review surface
- CGNAT head-end review surface
- topology-specific outer ownership review
- PKI review surface
- customer handoff package review

Pass criteria:

- both topologies build a combined review package
- package clearly indicates which side owns the outer tunnel

### Workstream C: PKI and Handoff

Support the certificate workflow required by both topologies.

Deliverables:

- `reference` mode support
- `local_generate` mode support
- customer-device handoff package generation
- gateway-device handoff package generation for `shared_isp_gateway`

Pass criteria:

- per-customer-outer topology produces customer outer cert bundle
- shared-ISP-gateway topology produces gateway outer cert bundle
- both topologies preserve inner PSK handoff needs

### Workstream D: Live-Apply Orchestration

Extend the shared deploy flow to handle both topologies without touching live
infrastructure yet.

Deliverables:

- target selection support
- apply-order support
- rollback-order support
- execution plan reporting

Pass criteria:

- staged apply works for both topologies
- rollback plan is complete for both topologies

### Workstream E: End-to-End Behavior Validation

Build and prove full end-to-end staged behavior before any real-node work.

Deliverables:

- staged end-to-end test harness
- feature parity matrix
- topology-specific validation checklists

Pass criteria:

- both topologies prove outer -> inner -> service flow in staged/lab mode
- full inner-service feature parity is demonstrated

## Phase Plan

### Phase 0: Baseline Freeze

Tasks:

- confirm current regression baseline
- confirm current docs are the source of truth
- freeze current examples and environment fixtures

Required gates:

- current `CGNAT/tests/run_tests.py` green
- current shared provisioning regression green
- current staged apply/rollback regression green

Artifacts:

- baseline regression summary
- baseline environment validation summary

### Phase 1: Topology-Aware Model

Tasks:

- extend schema/model for `outer_topology`
- add `outer_gateway_ref`
- preserve backend-family and NAT controls

Required tests:

- schema validation for both topologies
- legacy request validation
- customer-module rendering checks

Stop conditions:

- legacy request validation regression
- ambiguous topology defaults

Artifacts:

- request examples for both topologies
- rendered source/module fixtures

### Phase 2: Topology-Aware Packaging

Tasks:

- package per-customer-outer review flow
- package shared-ISP-gateway review flow
- ensure PKI/handoff artifacts reflect ownership correctly

Required tests:

- repo-only package generation for both topologies
- readiness and execution-plan consistency checks
- rollback artifact validation

Stop conditions:

- package does not clearly identify outer owner
- handoff bundle is incomplete

Artifacts:

- combined review summaries for both topologies
- PKI review artifacts
- customer or gateway handoff package manifests

### Phase 3: Staged Apply and Rollback

Tasks:

- extend staged apply for both topologies
- extend staged rollback for both topologies
- verify apply order and rollback order are explicit

Required tests:

- staged apply for `per_customer_outer`
- staged apply for `shared_isp_gateway`
- staged rollback for both

Stop conditions:

- rollback is incomplete
- apply order is ambiguous

Artifacts:

- staged execution plans
- staged rollback summaries

### Phase 4: Topology End-to-End Lab Harness

Tasks:

- create end-to-end test harness for:
  - `per_customer_outer`
  - `shared_isp_gateway`
- validate ownership boundaries
- validate path sequencing

Required tests:

#### Topology A: `per_customer_outer`

- customer outer cert tunnel up
- customer inner PSK tunnel up
- traffic reaches backend
- service path works

#### Topology B: `shared_isp_gateway`

- ISP gateway outer cert tunnel up
- customer inner PSK tunnel up
- traffic reaches backend through shared outer
- service path works

Stop conditions:

- outer ownership is not reflected in artifacts
- traffic path depends on hidden manual state

Artifacts:

- topology-specific test logs
- counter captures
- route/interface summaries

### Phase 5: Inner Service Feature Parity

Tasks:

- prove the inner tunnel retains normal backend service capabilities
- validate parity against direct customer behavior

Required tests:

For each topology, verify:

1. non-NAT inner service
2. NAT-T inner service
3. inside NAT enabled
4. inside NAT disabled
5. outside NAT enabled
6. outside NAT disabled
7. route-via / egress handoff behavior

Stop conditions:

- any CGNAT-backed service loses a feature direct customers already have

Artifacts:

- feature parity matrix
- pass/fail summary for each service capability

### Phase 6: Pre-Live Review Pack

Tasks:

- generate full review artifacts for both topologies
- assemble operator-facing checklists
- ensure rollback and backup instructions are complete

Required review artifacts:

- combined review summary
- execution plan
- live execution checklist
- rollback plan
- PKI review
- topology ownership summary
- feature parity matrix

Stop conditions:

- any artifact needed for operator review is missing
- backup instructions are incomplete

### Phase 7: Real-Node Readiness Gate

Tasks:

- hold a final Go / No-Go review
- confirm no unresolved blockers remain
- confirm both topology and service-parity gates are green

Required gates:

1. model gate green
2. packaging gate green
3. staged apply gate green
4. staged rollback gate green
5. end-to-end lab gate green
6. feature parity gate green
7. review artifact gate green

Exit criteria:

- we are ready to touch real nodes
- live scope and rollback scope are explicitly understood

## Test Matrix

The minimum matrix before any live-node work is:

| Area | Per-Customer Outer | Shared ISP Gateway |
|---|---|---|
| Schema / model | Required | Required |
| Repo-only package | Required | Required |
| PKI / handoff | Required | Required |
| Staged apply | Required | Required |
| Staged rollback | Required | Required |
| Outer tunnel bring-up | Required | Required |
| Inner tunnel bring-up | Required | Required |
| Service path | Required | Required |
| Non-NAT inner service | Required | Required |
| NAT-T inner service | Required | Required |
| Inside NAT | Required | Required |
| Outside NAT | Required | Required |

## Regression Discipline

For every implementation slice:

1. run the narrowest relevant tests first
2. if they fail, stop and fix before broadening scope
3. rerun the narrow tests
4. rerun the required broader gates
5. update docs and artifacts
6. only then advance

This is mandatory. No “we’ll clean it up in live” shortcuts.

## Stop Conditions

Execution must stop and return to fix/test mode if:

- direct customer regression fails
- topology ownership becomes ambiguous
- PKI ownership is unclear
- staged apply works but rollback does not
- inner service loses feature parity with direct customers
- topology behavior depends on hidden live/manual state
- review artifacts are incomplete

## Definition of Ready to Touch Real Nodes

We are ready to touch real nodes only when:

1. both CGNAT topologies are modeled and validated
2. both topologies have staged end-to-end proof
3. inner service feature parity is demonstrated
4. PKI and handoff behavior is complete for the chosen ownership model
5. rollback and backup instructions are explicit
6. all regression gates are green from one clean code state

At that point, we can move into a controlled live test-bed plan as a separate
execution step.
