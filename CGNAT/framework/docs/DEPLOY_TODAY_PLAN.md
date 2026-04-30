# Deploy Today Plan

## Purpose

This document turns the current CGNAT Scenario 1 work into a same-day
execution plan that gets us from review-ready code to the point where we can
apply to real infrastructure with confidence.

The goal is to keep moving, fix issues as they appear, and stop only for the
final human hard review before live apply.

## Architecture Reminder

The long-term architecture is:

- we host the CGNAT HEAD END
- one or more remote CGNAT ISP HEAD END peers connect to us
- we do not care what the remote public source IP is as long as the
  certificate identity is trusted
- the same ISP may use multiple certificates and therefore multiple outer
  tunnels when different traffic domains must stay separate
- the inner tunnels are the interesting traffic carried inside those outer
  access contexts
- the CGNAT HEAD END steers that inner traffic across GRE to the existing
  backend VPN head ends

Scenario 1 is the first deployable slice of that broader model.

## Target for Today

By the end of today we want to be at one of these two states:

1. ready to press the button on live apply after the final hard review
2. already through live AWS create and ready for host-side apply/validation

The work today should bias toward removing uncertainty, not adding new scope.

## Working Rules

- keep all code and docs inside `CGNAT/`
- do not touch muxer/backend code
- fix issues when they appear, document them, add tests where appropriate, and
  keep moving
- do not perform live apply until the review package is green and we have
  completed the hard look-over

## Phase A: Lock the Live Inputs

### Goal

Make sure the live bundle values are the exact ones we intend to use today.

### Checklist

- confirm hosted CGNAT HEAD END subnet
- confirm demo ISP-side subnet pair is same-AZ and acceptable
- confirm customer-facing public IP / backend public loopback target
- confirm backend class selection
- confirm GRE targets
- confirm AMI, key pair, instance profile, security groups
- confirm host access strategy

### Exit

- live bundle is final for today
- no guessed deployment values remain

## Phase B: Materialize Secrets and PKI

### Goal

Prepare the inputs the code already expects for host-side apply.

### Checklist

- generate demo outer-tunnel CA material on the CGNAT HEAD END side
- generate or stage remote outer-tunnel client cert/key material
- prepare inner VPN secret/key material for the demo customer side
- verify file paths and naming match the rendered server package expectations

### Exit

- demo PKI is ready
- inner VPN secret material is ready

## Phase C: Re-Run the Full Prep Path

### Goal

Regenerate all deployment artifacts using the final live inputs and secret
references.

### Checklist

- run Scenario 1 preparation flow
- run live AWS preflight
- run AWS dry-run apply
- rebuild host apply package
- rebuild remote apply plan
- rebuild predeploy review package

### Exit

- summary is green
- preflight is green
- AWS dry-run is green
- host apply package is current

## Phase D: Hard Review

### Goal

Do the last deliberate check before anything touches real infrastructure.

### Checklist

- architecture still matches intent
- live bundle values are correct
- AWS plan is clean
- AWS preflight is clean
- AWS dry-run is clean
- host-side artifacts look sane
- PKI and inner secret handling are understood
- rollback order is understood

### Exit

- explicit go to live AWS create

## Phase E: Live AWS Create

### Goal

Create the Scenario 1 infrastructure in AWS without yet applying host-side
config.

### Checklist

- execute AWS apply in live mode
- capture instance ids, ENIs, and EIP associations
- derive final host access from live results
- confirm instances are reachable and healthy

### Exit

- live EC2 infrastructure exists
- host access inputs are derived from reality

## Phase F: Host-Side Apply Readiness

### Goal

Be fully ready to push server-side configuration after infrastructure exists.

### Checklist

- stage rendered host apply bundles
- stage PKI and inner secret material to the correct hosts
- run host preflight commands
- confirm generated runtime values match live host facts

### Exit

- ready for host-side apply and validation

## Known Fast-Fail Conditions

These are same-day blockers that should stop us immediately if they appear:

- live bundle values are wrong or inconsistent
- PKI material cannot be generated or staged today
- inner VPN secret material is not available today
- AWS live preflight turns red
- AWS live apply fails to create the required instances or EIP actions
- derived host access cannot reach the created instances

## Recommended Execution Order

1. finalize live bundle values
2. materialize PKI and inner VPN secret inputs
3. rerun prep, preflight, and dry-run
4. do the hard review
5. perform live AWS create
6. derive host access
7. stage host apply inputs
8. pause only for the final host-side apply decision

## Bottom Line

We are not inventing a new plan today.

We are taking the existing Scenario 1 framework, locking the last live inputs,
proving the package one more time, and then moving through create and host-side
readiness in a controlled order.
