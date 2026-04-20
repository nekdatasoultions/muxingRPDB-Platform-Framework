# RPDB Head-End NAT Activation Redesign Project Plan

## Purpose

This plan is the next engineering block after the repo-only scale execution
plan.

The current explicit scale gate is honest and repeatable:

- muxer-side classification, translation, and bridge checks pass the current
  repo-only thresholds
- translated NAT-T customers using `nat_t_netmap` still fail the explicit scale
  gate at `1000`, `5000`, `10000`, and `20000`
- the failing checks are:
  - `headend_apply_commands`
  - `headend_rollback_commands`
  - `headend_max_apply_per_customer`

The goal of this plan is to redesign or batch the head-end post-IPsec NAT
activation backend so `nat_t_netmap` can pass the explicit scale gate without
weakening the customer behavior contract.

## Guardrails

- Stay inside this repository.
- Do not modify `MUXER3`.
- Do not touch AWS.
- Do not touch live or staging nodes.
- Do not deploy code.
- Do not apply a customer.
- Do not claim scale readiness until the explicit scale report turns green for
  the accepted target state.

## Current Problem Statement

The repo currently models translated NAT-T head-end activation as linear command
growth.

At `20000` `nat_t_netmap` customers, the measured repo-only result is:

- `80000` head-end apply commands
- `60000` head-end rollback commands
- `4` apply commands per customer

The current threshold policy expects:

- apply commands at or below `2 x customer_count`
- rollback commands at or below `2 x customer_count`
- max apply commands per customer equal to `2`

The core issue is not the customer NAT intent. The core issue is activation
shape: the head-end bundle still expands one customer into too many individual
apply and rollback commands.

## Target End State

The target end state is:

- customer YAML still describes NAT intent normally
- customer-scoped head-end artifacts still preserve:
  - one-to-one netmap behavior
  - explicit host-map behavior
  - route and mark carry-through
  - customer-scoped install, validate, and remove
- head-end NAT activation is batched through generated restore artifacts instead
  of line-by-line command expansion
- explicit scale gate no longer fails `nat_t_netmap`
- full repo verification passes
- work stops before deployment

## Phase 0. Preserve Baseline

Goal:

- keep the current verified state recoverable before changing the head-end NAT
  backend

Work:

- commit the current repo-only scale execution work
- confirm the repo baseline records the current `nat_t_netmap` failure
- keep generated render output out of source control

Gate:

- current work is committed
- explicit scale report still records the blocker honestly
- no AWS, nodes, customers, or `MUXER3` are touched

## Phase 1. Inventory Current Head-End NAT Artifact Shape

Goal:

- map every file and function that contributes to post-IPsec NAT activation

Work:

- inspect customer artifact rendering for:
  - `post-ipsec-nat/iptables-snippet.txt`
  - structured NAT intent files
  - apply and remove command manifests
- inspect head-end staged apply and remove scripts
- inspect validation logic that counts head-end apply and rollback commands
- document the exact command sources that produce `4` apply commands and `3`
  rollback commands per `nat_t_netmap` customer

Expected areas:

- `muxer/src/muxerlib/customer_artifacts.py`
- `scripts/deployment/apply_headend_customer.py`
- `scripts/deployment/remove_headend_customer.py`
- `muxer/scripts/run_scale_baseline.py`
- `muxer/scripts/run_repo_verification.py`
- `muxer/docs/TRANSLATION_AND_BRIDGE_SCALE_DECISIONS.md`

Gate:

- repo doc or code comments identify the current command source precisely
- no implementation starts until the current shape is understood

## Phase 2. Define The Batched Restore Contract

Goal:

- define a concrete restore-file contract that can replace per-command growth

Work:

- define generated files for apply and rollback, for example:
  - `post-ipsec-nat/iptables-restore.apply`
  - `post-ipsec-nat/iptables-restore.remove`
  - `post-ipsec-nat/activation-manifest.json`
- define customer-owned chain naming
- define include or jump points that keep unrelated customers untouched
- define how rollback removes only the selected customer chain
- define validation checks for generated restore files

Gate:

- the contract is specific enough to implement without guessing
- netmap and explicit host-map behavior are both represented
- unrelated customers remain out of scope for one-customer remove

## Phase 3. Implement Batched Artifact Rendering

Goal:

- render batched head-end NAT activation artifacts from the existing customer
  NAT intent

Work:

- add restore-file rendering for `netmap`
- add restore-file rendering for `explicit_host_map`
- keep the existing snippet as review/reference only if needed
- add a structured activation manifest with command counts and chain metadata
- update artifact validation to require the new restore artifacts when
  post-IPsec NAT is enabled

Gate:

- NAT and non-NAT customer artifact validation passes
- `nat_t_netmap` artifacts include restore files and activation manifest
- disabled NAT customers do not get unnecessary restore artifacts

## Phase 4. Implement Repo-Only Apply/Remove Semantics

Goal:

- make staged head-end apply/remove consume the batched restore contract instead
  of expanding per-rule shell commands

Work:

- update staged head-end apply helper to treat restore files as the activation
  unit
- update staged remove helper to use the remove restore file
- preserve validation and rollback journaling
- keep live execution disabled unless explicitly approved in later deployment
  work

Gate:

- staged apply writes the selected customer artifacts only
- staged remove removes the selected customer artifacts only
- rollback artifacts remain reviewable
- unrelated staged customers remain untouched

## Phase 5. Update The Scale Harness

Goal:

- make the scale harness measure the new batched activation model truthfully

Work:

- update `derive_post_ipsec_nat` measurement so batched restore activation is
  counted as the new activation unit
- preserve legacy command counts if useful as comparison fields
- keep max per-customer apply and rollback counts visible
- update `generate_scale_report.py` only if the threshold model needs a new
  metric name

Gate:

- `nat_t_netmap` reports reduced head-end apply and rollback growth
- the report still fails if the old per-command growth returns
- the threshold manifest remains explicit

## Phase 6. Run The Double Verification Loop

Goal:

- prove the fix is repeatable and not a one-off measurement

Work:

1. compile changed scripts
2. run the scale harness
3. generate the explicit scale report
4. run the full repo verification suite
5. rerun the scale harness
6. regenerate the explicit scale report
7. rerun the full repo verification suite
8. compare both scale reports

Gate:

- both scale reports agree
- explicit report is green for the accepted target state
- full repo verification passes twice

## Phase 7. Update Truthfulness Docs

Goal:

- keep docs aligned with the measured state

Work:

- update the scale report
- update the pre-deploy review package
- update the runtime completion plan
- update the scale gap audit

Gate:

- docs say exactly what passed and what remains open
- no deployment recommendation changes unless the explicit scale report supports
  it

## Definition Of Done

This project is complete when:

- current baseline is committed
- batched head-end NAT activation is implemented repo-only
- `nat_t_netmap` no longer fails the explicit scale gate for the accepted target
  state
- full repo verification passes twice
- docs reflect the measured result
- no AWS, nodes, customers, or `MUXER3` were touched
- the repo remains stopped before deployment

## Stop Point

Stop after the repo-only gate is green.

Do not:

- deploy code
- touch AWS
- touch nodes
- apply a customer
- modify `MUXER3`

If the gate cannot be made green without changing the accepted architecture,
stop and write a new problem statement before changing thresholds or design
assumptions.
