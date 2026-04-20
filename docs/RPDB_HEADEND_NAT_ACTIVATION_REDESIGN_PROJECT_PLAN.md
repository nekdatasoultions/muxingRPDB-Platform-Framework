# RPDB Head-End NAT nftables Redesign Project Plan

## Purpose

This plan corrects the previous drift where the head-end post-IPsec NAT plan
defaulted back to `iptables-restore`.

The corrected direction is:

- `nftables` is the primary and only accepted backend for head-end post-IPsec
  NAT in the RPDB scale design
- `iptables-restore` is not a viable fallback
- `MUXER3` is not a viable implementation fallback
- if a required behavior cannot be represented safely in `nftables`, the work
  must stop for a written problem statement and new design decision instead of
  falling back to `iptables-restore`

Plain guardrail: iptables-restore is not a viable fallback.
Plain guardrail: MUXER3 is not a viable implementation fallback.

The current explicit scale gate is honest and repeatable:

- muxer-side classification, translation, and bridge checks pass the current
  repo-only thresholds
- translated NAT-T customers using `nat_t_netmap` still fail the explicit scale
  gate at `1000`, `5000`, `10000`, and `20000`
- the failing checks are:
  - `headend_apply_commands`
  - `headend_rollback_commands`
  - `headend_max_apply_per_customer`

The goal of this project is to make the translated NAT-T head-end activation
path scale through batched `nftables` artifacts, while preserving customer NAT
semantics.

## Guardrails

- Stay inside this repository.
- Do not modify `MUXER3`.
- Do not use `MUXER3` as a runtime, implementation, or deployment fallback.
- Do not touch AWS.
- Do not touch live or staging nodes.
- Do not deploy code.
- Do not apply a customer.
- Do not claim scale readiness until the explicit scale report turns green for
  the accepted target state.
- Do not reintroduce `iptables-restore` as an implementation or fallback path.
- Treat `docs/RPDB_CORE_ENGINEERING_GUARDRAILS.md` as the standing guardrail
  contract for this workstream.

## Problem Statement

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

The issue is not the customer NAT intent. The issue is activation shape and
backend choice: the head-end NAT path still behaves like rule-by-rule
`iptables` activation instead of a batched `nftables` state update.

## Required Technology Direction

The primary technologies for this fix are:

- Linux `nftables`
- `nft -f` batch files
- `nftables` tables, chains, sets, and maps
- generated repo artifacts that are reviewable before deployment
- repo-only staged apply/remove validation
- the existing scale harness and explicit scale report

The disallowed implementation and fallback paths are:

- `iptables-restore`
- `MUXER3`
- the legacy head-end `iptables` activation model

If `nftables` cannot satisfy a required behavior:

- stop the implementation
- write a problem statement
- create a new design decision for review
- do not add an `iptables-restore` fallback

## Target End State

The target end state is:

- customer YAML still describes NAT intent normally
- customer-scoped head-end artifacts preserve:
  - one-to-one netmap behavior
  - explicit host-map behavior
  - route and mark carry-through
  - customer-scoped install, validate, and remove
- head-end NAT activation is represented by generated `nftables` artifacts
- apply and rollback use batched `nft -f` semantics in repo-modeled form
- explicit scale gate no longer fails `nat_t_netmap`
- full repo verification passes twice
- work stops before deployment

## Phase 0. Preserve And Correct The Baseline

Goal:

- keep the current verified state recoverable while correcting the head-end NAT
  direction

Work:

- confirm the current baseline commit exists
- update docs that still say the default is `iptables-restore`
- keep generated render output out of source control
- preserve the current failing scale evidence as the reason for this work

Gate:

- docs state `nftables` is the primary backend
- docs state `iptables-restore` is prohibited, not a fallback
- docs state `MUXER3` is prohibited as an implementation or deployment fallback
- explicit scale report still records the current blocker honestly
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

## Phase 2. Define The nftables NAT Contract

Goal:

- define a concrete `nftables` contract that replaces per-command growth

Work:

- define generated files for apply and remove, for example:
  - `post-ipsec-nat/nftables.apply.nft`
  - `post-ipsec-nat/nftables.remove.nft`
  - `post-ipsec-nat/nftables-state.json`
  - `post-ipsec-nat/activation-manifest.json`
- define table and chain naming
- define customer-owned set and map names
- define how one-to-one netmap intent is represented in `nftables`
- define how explicit host-map intent is represented in `nftables`
- define how customer-scoped remove deletes only the selected customer state
- define validation checks for generated `nftables` files

Gate:

- the `nftables` contract is specific enough to implement without guessing
- netmap and explicit host-map behavior are both represented
- unrelated customers remain out of scope for one-customer remove
- no `iptables-restore` activation path is accepted
- no `MUXER3` dependency is accepted

## Phase 3. Prove nftables Semantic Compatibility Repo-Only

Goal:

- prove that `nftables` can represent the required NAT semantics before changing
  the artifact generator

Work:

- add repo-only fixtures for:
  - one-to-one subnet translation
  - single host explicit mapping
  - multiple host explicit mapping
  - route and mark carry-through metadata
- render expected `nftables` state for each fixture
- validate that the rendered state preserves customer intent
- if a semantic cannot be represented, write a problem statement before any
  implementation direction changes

Gate:

- all required NAT semantics have passing repo fixtures
- or the work stops with a documented problem statement and new design gate

## Phase 4. Implement nftables Artifact Rendering

Goal:

- render batched head-end NAT activation artifacts from the existing customer
  NAT intent

Work:

- add `nftables` rendering for `netmap`
- add `nftables` rendering for `explicit_host_map`
- do not keep or rely on `iptables-restore` as a compatibility fallback
- add a structured activation manifest with:
  - backend type
  - table name
  - chain names
  - set names
  - map names
  - estimated activation units
- update artifact validation to require the new `nftables` artifacts when
  post-IPsec NAT is enabled

Gate:

- NAT and non-NAT customer artifact validation passes
- `nat_t_netmap` artifacts include `nftables` files and activation manifest
- disabled NAT customers do not get unnecessary `nftables` NAT artifacts
- old `iptables` snippets are not counted as the primary activation backend

## Phase 5. Implement Repo-Only Apply/Remove Semantics

Goal:

- make staged head-end apply/remove consume the `nftables` contract instead of
  expanding per-rule shell commands

Work:

- update staged head-end apply helper to treat `nftables` files as the
  activation unit
- update staged remove helper to use the generated remove batch
- preserve validation and rollback journaling
- keep live execution disabled unless explicitly approved in later deployment
  work

Gate:

- staged apply writes the selected customer artifacts only
- staged remove removes the selected customer artifacts only
- rollback artifacts remain reviewable
- unrelated staged customers remain untouched
- repo-modeled apply/remove does not default back to `iptables-restore`
- repo-modeled apply/remove has no `MUXER3` dependency

## Phase 6. Update The Scale Harness

Goal:

- make the scale harness measure the new batched `nftables` activation model
  truthfully

Work:

- update `derive_post_ipsec_nat` measurement so `nftables` batch activation is
  counted as the new activation unit
- preserve legacy command counts as comparison fields if useful
- keep max per-customer apply and rollback counts visible
- update `generate_scale_report.py` only if the threshold model needs a new
  metric name

Gate:

- `nat_t_netmap` reports reduced head-end apply and rollback growth
- the report still fails if the old per-command growth returns
- the threshold manifest remains explicit

## Phase 7. Run The Double Verification Loop

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

## Phase 8. Update Truthfulness Docs

Goal:

- keep docs aligned with the measured state

Work:

- update the scale report
- update the pre-deploy review package
- update the runtime completion plan
- update the scale gap audit
- update the translation and bridge decision record

Gate:

- docs say exactly what passed and what remains open
- no deployment recommendation changes unless the explicit scale report supports
  it

## Definition Of Done

This project is complete when:

- current baseline is committed
- head-end post-IPsec NAT activation is implemented repo-only through
  `nftables`
- `iptables-restore` is not present as an implementation or fallback path
- `MUXER3` is not present as an implementation or deployment fallback path
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
