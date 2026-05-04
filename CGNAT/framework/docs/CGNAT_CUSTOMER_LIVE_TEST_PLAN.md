# CGNAT Customer Live Test Plan

## Purpose

This document defines the guarded path for the first controlled live CGNAT
customer rollout and the follow-on expansion to a second customer.

The intended sequence is:

1. use **CGNAT customer 1** as the canary
2. prove the full platform-side and customer-device handoff path
3. only then allow the same flow to be reused for **customer 2**

## Scope Boundary

The shared provisioning flow owns:

- backend VPN head-end customer state
- muxer customer state
- CGNAT head-end customer state
- PKI review artifacts
- customer handoff package generation

It does **not** own direct login/apply on the customer device. Customer-device
installation remains a controlled manual or operator-driven step that consumes
the generated handoff package.

## Required Guard Rails

Before any live change:

1. all regression gates must be green
2. the repo-only customer review package must be green
3. the live execution checklist must exist
4. platform backups must be captured and verified
5. customer-device backups must be captured and verified
6. rollback ownership must be explicit

## Customer 1 Canary Sequence

### Phase A: Pre-Live Review

- validate the customer 1 request
- review:
  - combined review summary
  - PKI review
  - live test-bed plan
  - live execution checklist
- verify customer 1 handoff package contents

### Phase B: Backup Capture

Platform-side:

- muxer
- backend active head end
- backend standby head end
- CGNAT head end

Customer-device side:

- current outer tunnel config
- current certificate, key, and CA files
- current routing and interface state
- current SA state / daemon status

### Phase C: Platform Apply

Apply in this order:

1. backend customer state
2. muxer customer state
3. CGNAT head-end customer state

Stop after each surface if validation is not green.

### Phase D: Customer 1 Handoff Install

Use the generated customer handoff package.

Rules:

- do not remove the old customer state first
- stage the new customer state side by side where possible
- validate the new outer tunnel before retiring the previous customer config

### Phase E: Customer 1 Validation

Required validation order:

1. outer tunnel certificate identity and trust
2. backend inner tunnel state
3. service-path traffic and counters
4. rollback viability

### Phase F: Customer 1 Exit Criteria

Customer 1 is considered green only when:

- the outer tunnel establishes with the expected identity and trust chain
- the platform-side surfaces validate cleanly
- the inner tunnel validates cleanly
- service-path traffic works as expected
- rollback remains available

## Customer 2 Promotion Rule

Customer 2 may only proceed after customer 1 is green.

Promotion requirements:

1. customer 1 canary complete
2. customer 1 rollback plan reviewed after validation
3. no unresolved cert/identity collision issues
4. no unresolved platform-side regression

## Customer 2 Plan

Customer 2 should reuse the same guarded shape:

1. generate customer 2 review package
2. verify unique PKI refs and handoff package
3. capture customer 2 backups
4. apply platform state only if the customer 2 delta requires it
5. install customer 2 handoff package
6. validate outer -> inner -> service

## Stop Conditions

Stop and return to fix/test mode if:

- customer 1 outer tunnel identity does not match expected cert state
- customer 1 service validation fails
- customer 2 review shows reused or conflicting identity/auth refs
- staged dual-customer regression is not green
- rollback artifacts are incomplete

## Operational Artifacts

The per-request repo-only review flow should produce:

- `combined-review-summary.json`
- `live-test-bed-plan.json`
- `live-execution-plan.json`
- `LIVE_EXECUTION_CHECKLIST.md`
- `pki/pki-review.json`

These artifacts are the required operator inputs before any live apply.
