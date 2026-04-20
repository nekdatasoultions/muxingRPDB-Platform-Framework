# RPDB Scale Repo-Only Execution Plan

## Purpose

This document is the execution plan for finishing the remaining RPDB scale
work inside this repository only.

It is intentionally scoped to:

- `muxingRPDB Platform Framework-main`
- repo-only code, docs, tests, and verification artifacts
- no `MUXER3` changes
- no AWS changes
- no node access
- no customer deployment
- no code rollout to muxer or head-end systems

The goal is to get to:

- implemented repo code
- integrated repo verification
- measured scale evidence
- a deployment review package

and then stop short of deploying that code anywhere.

## Current Baseline

Already complete in repo-only form:

- customer-scoped control-plane model
- allocator-backed provisioning flow
- customer-scoped pass-through `show-customer`, `apply-customer`, and
  `remove-customer`
- strict DynamoDB no-scan boundary for customer-scoped runtime commands
- synthetic scale baseline harness
- corrected project status that says the scalable dataplane backend is still
  incomplete

Still open:

- head-end post-IPsec NAT activation batching or backend redesign for
  `nat_t_netmap`
- live-node proof outside the repo-only execution boundary
- final deployment decision remains blocked until the explicit scale report is
  green for the accepted target state

## Current Execution Result

As of `2026-04-19`, the repo-only execution state is:

- Phases 0 through 6 are implemented and verified in repo-only form
- Phase 7 is implemented and double-checked, and the explicit report truthfully
  says `failed`
- the only failing evaluations in the explicit report are the `nat_t_netmap`
  scenarios at `1000`, `5000`, `10000`, and `20000`
- the failing checks are head-end apply command count, head-end rollback
  command count, and max apply commands per customer
- Phase 8 stops with a no-go pre-deploy review package instead of pretending the
  remaining scale blocker is solved

## Guardrails

- Do not modify `MUXER3`.
- Do not touch AWS.
- Do not touch live or staging nodes.
- Do not copy or deploy code outside this repository.
- Do not claim the scale problem is solved until the scale gates in this plan
  pass.
- Do not move to the next phase until the current gate passes twice.

## Definition Of Done

This plan is complete when all of these are true:

- the pass-through classification layer has a real repo-implemented `nftables`
  backend
- the translation and bridge stages have a documented and implemented growth
  strategy
- the normal live apply model is no longer designed around raw SSH/SCP shell
  fan-out
- atomicity and rollback behavior are documented, implemented, and tested
- the repo contains measured scale reports for 1k, 5k, 10k, and 20k scenarios
- the repo contains a pre-deploy review package
- we stop before any live deployment or node rollout

## Standard Gate Rule

Every phase in this plan uses the same rule:

1. implement the phase in repo code and docs
2. run the phase-specific verification
3. run the full repo verification suite
4. rerun the phase-specific verification a second time
5. rerun the full repo verification suite a second time
6. if anything fails:
   - write a short problem statement
   - write a corrective mini-plan
   - fix the problem in the repo
   - rerun the same gate from the start
7. only then move to the next phase

## Phase 0. Freeze The Boundary

Goal:

- keep the repo honest about what is complete and what is not

Deliverables:

- current correction note remains the source of truth
- runtime completion docs remain aligned with the corrected boundary
- scale baseline harness remains part of repo verification

Primary files:

- `docs/RPDB_SCALE_GAP_AUDIT_AND_PROJECT_PLAN.md`
- `muxer/docs/RUNTIME_COMPLETION_PLAN.md`
- `muxer/docs/SCALE_BASELINE_HARNESS.md`
- `muxer/scripts/run_repo_verification.py`

Gate:

- repo docs consistently describe RPDB as:
  - customer-scoped control-plane progress complete enough for repo-only pilot
  - scalable dataplane backend still incomplete

Current status:

- complete

## Phase 1. Finish Pass-Through Classification Backend In `nftables`

Goal:

- move pass-through peer classification, mark selection, and default-drop
  behavior from preview-only render into the real repo apply path

Work:

- review the current preview model in:
  - `muxer/runtime-package/src/muxerlib/nftables.py`
  - `muxer/runtime-package/scripts/render_nft_passthrough.py`
- define the supported pass-through classification surface:
  - peer match
  - protocol-aware mark assignment
  - default-drop behavior
- add a runtime backend selector for classification mode
- make pass-through apply/remove use the `nftables` backend for that layer
- keep renderable review artifacts for diffs and troubleshooting
- preserve the current legacy path only as an explicit compatibility backend

Expected code areas:

- `muxer/runtime-package/src/muxerlib/nftables.py`
- `muxer/runtime-package/src/muxerlib/modes.py`
- `muxer/runtime-package/src/muxerlib/core.py`
- `muxer/runtime-package/src/muxerlib/cli.py`
- `muxer/runtime-package/config/muxer.yaml`
- `muxer/scripts/run_repo_verification.py`
- `muxer/scripts/run_scale_baseline.py`

Phase-specific verification:

- render and validate the `nftables` batch script for synthetic strict non-NAT,
  NAT-T, and mixed customers
- prove the pass-through classification apply path selects `nftables`
- prove the legacy per-customer `iptables` mark/accept/default-drop layer is no
  longer emitted by the new backend path

Gate:

- pass-through classification is repo-implemented through `nftables`
- the repo verification suite proves the backend selection
- the scale harness records reduced classification-layer linear growth relative
  to the current baseline

Current status:

- complete
- customer-scoped and fleet pass-through apply paths now select the repo-modeled
  live `nftables` classification backend
- focused phase verification passed twice
- full repo verification passed twice with the new backend enabled

## Phase 2. Close Translation And NFQUEUE Design

Goal:

- explicitly decide how the remaining translation and bridge layers scale before
  implementing them

Work:

- break the remaining dataplane into:
  - muxer translation path
  - NFQUEUE bridge path
  - head-end post-IPsec NAT path
- document the growth behavior of each path from the current baseline
- decide for each path whether it will use:
  - `nftables`
  - a reduced `iptables` compatibility backend
  - a dedicated helper/service model
  - a staged hybrid model with a clear exit path
- document why the chosen path is acceptable for 20k-scale goals

Expected code and doc areas:

- `muxer/runtime-package/src/muxerlib/dataplane.py`
- `muxer/runtime-package/src/muxerlib/modes.py`
- `muxer/runtime-package/src/muxerlib/nftables.py`
- `docs/RPDB_SCALE_GAP_AUDIT_AND_PROJECT_PLAN.md`
- new design note under `muxer/docs/`

Phase-specific verification:

- repo contains a design decision document for each of the three layers
- scale harness output is mapped to those decisions

Gate:

- a written design decision exists for:
  - muxer translation
  - NFQUEUE bridge
  - head-end NAT
- the decision is specific enough to implement without guessing

Current status:

- complete
- the decision record exists in `muxer/docs/TRANSLATION_AND_BRIDGE_SCALE_DECISIONS.md`
- the later repo verification steps use that decision record as the reference
  point for backend comparison and explicit scale reporting

## Phase 3. Implement The Chosen Translation Strategy Repo-Only

Goal:

- reduce the largest remaining per-customer translation growth area in code

Work:

- implement the chosen muxer translation backend from Phase 2
- preserve customer behavior semantics for:
  - strict non-NAT
  - NAT-T
  - reply-path handling
  - customer-scoped remove
- add render/review artifacts so translation changes remain diffable
- update the scale harness to measure the new translation path separately from
  the classification path

Expected code areas:

- `muxer/runtime-package/src/muxerlib/dataplane.py`
- `muxer/runtime-package/src/muxerlib/modes.py`
- `muxer/runtime-package/src/muxerlib/nftables.py`
- `muxer/scripts/run_scale_baseline.py`
- `muxer/scripts/run_repo_verification.py`

Phase-specific verification:

- translated synthetic customers still derive correctly
- remove path cleans up only the selected customer translation state
- scale harness shows translation growth changes compared with the old baseline

Gate:

- the chosen translation strategy is repo-implemented
- customer-scoped apply/remove remains correct in repo verification
- new scale artifact shows the intended translation-layer behavior

Current status:

- complete in repo code
- customer-scoped and fleet pass-through apply paths now emit `0` legacy muxer
  translation rules for the strict non-NAT and NAT-T synthetic profiles
- the verifier compares the active backend against the Phase 2 compatibility
  baseline and the full legacy baseline

## Phase 4. Implement The NFQUEUE Bridge Strategy Repo-Only

Goal:

- stop treating the bridge logic as an unexamined legacy sidecar

Work:

- implement the chosen NFQUEUE bridge strategy from Phase 2
- isolate bridge state so customer-scoped operations remain delta-based
- make the bridge path measurable in the scale harness
- document how bridge behavior interacts with NAT-T and translated customers

Expected code areas:

- `muxer/runtime-package/src/muxerlib/modes.py`
- `muxer/runtime-package/src/muxerlib/dataplane.py`
- `muxer/runtime-package/src/muxerlib/core.py`
- `muxer/scripts/run_scale_baseline.py`
- `muxer/scripts/run_repo_verification.py`

Phase-specific verification:

- repo-only customer apply/remove exercises the bridge path where appropriate
- bridge-related rules or objects are counted separately in the scale harness
- no customer-scoped operation regresses into full-fleet rebuild behavior

Gate:

- NFQUEUE bridge strategy is implemented and measured
- customer-scoped delta operations remain intact

Current status:

- complete in repo code
- the scale harness now measures bridge-specific profiles separately
- the active backend emits `0` legacy bridge rules for the synthetic bridge
  profiles under the current repo-modeled backend

## Phase 5. Replace Shell Fan-Out In The Design With A Node-Local Apply Model

Goal:

- remove raw SSH/SCP shell fan-out as the intended normal apply architecture

Work:

- define the target activation model, for example:
  - node-local apply service
  - pull-based bundle activation
  - journaled local agent
- change the repo orchestration code so the primary model is that new local
  activation path
- keep existing SSH/SCP logic only as an explicit break-glass compatibility path
- define the bundle handoff contract, activation journal, and rollback journal

Expected code areas:

- `scripts/customers/deploy_customer.py`
- `scripts/customers/live_apply_lib.py`
- `scripts/customers/live_access_lib.py`
- `scripts/customers/live_backend_lib.py`
- relevant docs under `docs/` and `muxer/docs/`

Phase-specific verification:

- repo-only approved-apply path uses the new activation contract in staged form
- journaling and rollback artifacts are generated from the new path
- SSH/SCP path is no longer the default modeled backend

Gate:

- the repo's primary normal apply architecture is no longer shell fan-out
- staged verification proves the new activation path end to end

Current status:

- complete in repo-only staged form
- the primary modeled apply path is the node-local activation-bundle contract
  with apply and rollback journals
- compatibility remote delivery paths still exist, but they are no longer the
  default modeled backend in staged verification

## Phase 6. Add Atomicity And Failure Containment

Goal:

- make partial apply failures bounded and predictable

Work:

- add batch activation where the backend supports it
- add staged activation where full atomicity is not possible
- tighten rollback ordering across:
  - backend
  - muxer
  - head end
- extend failure injection coverage for:
  - translation failures
  - bundle activation failures
  - validation failures

Expected code areas:

- `scripts/customers/live_apply_lib.py`
- `scripts/customers/live_backend_lib.py`
- `muxer/scripts/run_repo_verification.py`
- any new test fixtures under `build/repo-verification/`

Phase-specific verification:

- forced-failure tests leave no orphaned customer state in staged verification
- rollback journals are complete and reviewable
- repeated failure runs behave the same way twice

Gate:

- bounded rollback behavior is proven in repo-only verification
- failure containment is documented and repeatable

Current status:

- complete
- staged approval-path verification proves rollback journals, repeated forced
  failure behavior, and targeted cleanup without orphaned staged customer state

## Phase 7. Create Real Scale Gates

Goal:

- replace generic scale claims with explicit thresholds and reports

Work:

- extend the scale harness outputs to include:
  - rule or set or map counts
  - apply latency
  - remove latency
  - rollback latency
  - peak CPU where measurable repo-only
  - peak memory where measurable repo-only
- define explicit thresholds for:
  - 1k
  - 5k
  - 10k
  - 20k
- generate a committed repo report that says pass or fail at each level

Expected code and artifact areas:

- `muxer/scripts/run_scale_baseline.py`
- `muxer/scripts/run_repo_verification.py`
- `build/scale-baseline/`
- new scale report doc under `docs/` or `muxer/docs/`

Phase-specific verification:

- every target scale point has a report entry
- pass/fail thresholds are machine-checked in repo verification
- reports are generated twice and agree

Gate:

- scale report exists in the repo
- thresholds are explicit
- the report says pass or fail without interpretation drift

Current status:

- complete in repo-only form
- the explicit report exists and is machine-checked
- the current report status is `failed`
- the only failed evaluations are `nat_t_netmap` at `1000`, `5000`, `10000`,
  and `20000`
- the failing checks are:
  - `headend_apply_commands`
  - `headend_rollback_commands`
  - `headend_max_apply_per_customer`

## Phase 8. Pre-Deploy Review Package

Goal:

- finish with a truthful pre-deploy review package and stop there

Work:

- collect:
  - updated architecture statement
  - current runtime completion status
  - scale report
  - translation and bridge design decisions
  - apply activation design
  - rollback and failure-containment notes
- write a final pre-deploy review checklist covering:
  - what changed
  - what remains open
  - what was proven repo-only
  - what still requires live validation
- explicitly state the stop point:
  - no node rollout
  - no customer apply
  - no AWS action

Expected output:

- one consolidated review package in `docs/`

Gate:

- the repo contains a deployment review package
- the package is sufficient for human approval review
- work stops before any live deployment

Current status:

- complete
- the repo now contains a truthful pre-deploy review package and explicit scale
  report package for the corrected head-end NAT activation path
- the current repo-only scale recommendation is `passed, still gated before
  live deployment`

## Stop Point

When Phase 8 passes, stop.

The current stop result is:

- no AWS action
- no node rollout
- no customer apply
- no `MUXER3` changes
- no live deployment until a separate live-node validation plan is approved

Do not:

- deploy to RPDB nodes
- touch AWS
- apply a customer
- change `MUXER3`

At that point the repo should be review-ready, but still not deployed.

## Immediate Next Step

There is no further repo-only execution step in this plan before live-node
validation planning.

If work resumes after this stop point, the next engineering task is:

- prepare a live-node validation plan for the new RPDB muxer and VPN head ends
- validate nftables syntax and rollback behavior on non-customer test artifacts
- only then reopen customer deployment review
