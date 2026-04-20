# RPDB Scale Gap Audit And Project Plan

## Purpose

This document is a correction note and a forward project plan.

It separates:

- what the RPDB repo actually implements today
- what the RPDB architecture said should be implemented for real scale
- what was only partially implemented or left as a preview path
- what must be finished before we claim the platform is ready for larger-scale
  customer migration

## Executive Correction

The RPDB repo is materially better than the old `MUXER3` workflow in the control
plane, but it is not yet complete enough to honestly claim that the scaling work
is finished.

What is real today:

- customer-scoped source, allocation, render, and deployment orchestration
- explicit `rpdb_priority` support
- customer-scoped muxer apply/remove for pass-through mode
- customer-scoped backend and head-end artifact preparation and apply
- automatic NAT-T observation and orchestration path support

What is not finished:

- the scalable live dataplane backend
- the move away from large linear live `iptables` programming
- batch or atomic dataplane application
- removal of shell fan-out as the normal live apply backend
- proof that the current runtime is ready for very large customer counts

So the honest state is:

- the customer control plane changed a lot
- the live dataplane backend did not change enough yet to call the scale problem
  solved

## What The Target Architecture Said

The target architecture explicitly called out the main scaling pain points:

- monolithic customer authoring
- full-fleet render/apply behavior
- one-customer-at-a-time shell command fan-out
- implicit RPDB rule priorities
- large linear `iptables` growth

It also said the new model should move away from large numbers of individual
shell command insertions and toward:

- batch updates
- atomic application where possible
- eventual `nftables` set and map usage instead of very large linear rule lists

See:

- [RPDB_TARGET_ARCHITECTURE.md](./RPDB_TARGET_ARCHITECTURE.md)

## What Is Actually Implemented

### 1. Customer-scoped control plane

This part is real.

The repo now has a one-customer request, allocation, render, validation, and
deployment model. That is a real improvement over the old fleet-oriented path.

Implemented areas include:

- one customer source file per customer
- one canonical customer item model
- resource allocation tracking for marks, tables, priorities, tunnel keys, and
  related namespaces
- one-command dry-run and approved deploy orchestration
- customer-scoped muxer/head-end/backend apply and rollback helpers

### 2. Explicit RPDB priority support

This part is also real.

The runtime now supports explicit `rpdb_priority` values instead of relying only
on kernel-assigned rule ordering.

### 3. Customer-scoped pass-through muxer writes

This part is real, but scoped.

For the migration-relevant `pass_through` mode, the muxer runtime now supports:

- `show-customer`
- `apply-customer`
- `remove-customer`

Those are delta-oriented relative to one selected customer.

### 4. NAT-T orchestration path

This part is real.

The repo contains a watcher/orchestrator path that can detect UDP/4500
observations and call the same customer deploy flow used for reviewed customer
packages.

## What Is Still Missing Or Only Partial

### Gap 1. The live dataplane still uses linear `iptables` programming

This is the biggest unresolved scale gap.

The runtime completion plan already admits this directly:

- normal loading still has legacy boundaries
- the live dataplane still includes legacy linear programming
- the pass-through classification layer now uses a repo-modeled live
  `nftables` backend, but the remaining rewrite and bridge stages are still
  legacy

The code matches that statement.

The muxer runtime still programs per-customer `iptables` rules for:

- `DNAT`
- `SNAT`
- `NFQUEUE`

and it does so in per-rule shell calls.

That means the rule count still grows with customer count, protocol mix, and
head-end egress sources.

### Gap 2. Only the first `nftables` layer is implemented

The repo now uses `nftables` in the pass-through apply path for:

- peer classification
- fwmark maps
- default-drop behavior

That closes the classification-only part of the gap, but the rewrite and
bridge logic still stays on the legacy path.

### Gap 3. Shell fan-out still exists as a compatibility delivery path

The target architecture said the old shape would get painful because of
one-customer-at-a-time shell command fan-out.

The repo now has a node-local activation-bundle contract and staged journaling
path, but the compatibility live-delivery path still does this when used:

- write to DynamoDB
- prepare artifacts locally
- copy payloads over SSH/SCP
- run remote apply/validate/remove scripts on the muxer
- run remote apply/validate/remove scripts on active and standby head ends

That is a much safer workflow than before, and it is no longer the primary
repo-modeled staged activation path, but it is still present as a compatibility
delivery model that has not been proven away on live nodes.

### Gap 4. Normal all-customer loading still uses DynamoDB scan

The customer command model and runtime completion plan both already call this
out.

Single-customer lookup support exists, but the all-customer loader still uses a
table scan. That means the repo improved the normal customer path without fully
eliminating fleet-scan behavior from the runtime.

This matters because one of the original goals was to stop treating normal
operations as full-table operations.

### Gap 5. Head-end post-IPsec NAT relied on `iptables` snippets

This gap has been corrected in repo-only code.

The head-end orchestration model now renders:

- `post-ipsec-nat/nftables.apply.nft`
- `post-ipsec-nat/nftables.remove.nft`
- `post-ipsec-nat/nftables-state.json`
- `post-ipsec-nat/activation-manifest.json`

for customer-scoped:

- one-to-one translated subnet maps
- explicit host maps
- route and mark carry-through metadata

The repo still stops before live deployment, but the active bundle and staged
head-end path no longer uses a head-end `iptables` snippet as the post-IPsec NAT
activation model.

### Gap 6. The repo now has real scale gates, and they still show one open large-scale blocker

The repo now contains explicit RPDB proof artifacts for:

- rule and object counts
- apply latency
- remove latency
- rollback latency
- memory growth
- CPU growth
- behavior at 1k, 5k, 10k, and 20k customer counts

Those artifacts now prove something more useful than a generic claim:

- muxer-side classification, translation, and bridge behavior currently pass the
  explicit repo thresholds
- translated NAT-T customers using `nat_t_netmap` now pass the affected
  explicit head-end post-IPsec NAT activation gate in the targeted repo-only
  scale run

So the honest statement is still not "RPDB is ready to deploy."

The honest statement is:

- RPDB has a much better control plane
- RPDB now has explicit scale evidence
- the head-end NAT activation path is no longer the measured repo-only blocker
  for `nat_t_netmap`
- RPDB still requires full repo verification and then separate live-node
  validation before any customer deployment

## Why Earlier Validation Could Still Pass

This is the key correction.

The repo contains a mismatch between the high-level target architecture and the
later runtime completion gate.

The target architecture says the scaling problem includes:

- shell fan-out
- large linear `iptables` growth
- lack of batch and atomic dataplane programming

But the runtime completion plan later lowers the migration gate to:

- normal customer operations do not depend on full-table scan
- one customer can be applied without rebuilding all customers
- one customer can be removed without rebuilding all customers
- the dataplane path is at least delta-based, even if `nftables` migration is
  still in progress

That means the repo could honestly validate:

- customer-scoped add/remove
- delta-oriented pass-through apply/remove
- reviewed customer packaging
- deployment orchestration

while still not having finished:

- the scalable live dataplane backend

So the validation that passed was a narrower pass-through migration gate, not a
full architectural completion gate for large-scale growth.

## What This Means For The 20k Goal

If the goal is truly to support growth well beyond the old model, then the
unfinished pieces above are not optional cleanup items.

They are the core remaining work.

The current repo likely improves:

- onboarding safety
- rollback safety
- namespace tracking
- customer-by-customer blast radius
- operator workflow

But the current repo does not yet prove that the live dataplane can scale cleanly
to very large customer counts, because:

- the NFQUEUE bridge path is still programmed through legacy per-customer
  queue-rule semantics
- head-end post-IPsec NAT activation still expands linearly in command count
- the live deploy path still shells out across nodes
- there is no measured large-scale pass/fail gate in the repo today

## Project Plan

### Phase 0. Correct The Boundary

Goal:

- stop claiming the large-scale dataplane problem is solved

Deliverables:

- this audit document
- update any future project status to say:
  - customer-scoped control plane is implemented
  - scalable dataplane backend is not complete

Gate:

- all future project communication uses the corrected boundary

### Phase 1. Create A Scale Baseline Harness

Goal:

- measure the current runtime honestly before changing it

Deliverables:

- synthetic customer generator for pass-through customers
- local render/apply benchmark harness
- counters for:
  - number of generated classification rules
  - number of generated NAT rules
  - number of shell commands issued
  - apply/remove runtime
  - memory/CPU snapshots where practical

Gate:

- repeatable benchmark runs for 100, 1k, 5k, 10k, and 20k synthetic customers
- saved benchmark summary artifact in the repo

### Phase 2. Remove Normal Fleet Scan From Normal Runtime Paths

Goal:

- ensure normal customer operations never require table scan

Work:

- make single-customer get/put/delete the normal runtime contract
- keep full scan only for explicit fleet/admin/export commands
- verify customer-scoped apply/remove/show paths do not fall back to full scan

Gate:

- repo verification proves customer-scoped operations use direct key lookups
- explicit fleet scan is isolated behind an explicit admin command path

### Phase 3. Finish The Live `nftables` Backend For Pass-Through Classification

Goal:

- replace the first layer of live pass-through `iptables` classification with a
  real `nftables` backend

Work:

- promote the current preview renderer into a real live apply backend
- apply peer classification, mark maps, and default-drop behavior through
  batched `nft` updates
- preserve repo-only rendering and review artifacts for diffability

Gate:

- pass-through accept/mark/default-drop behavior is applied live through
  `nftables`
- live muxer apply no longer emits per-customer `iptables` mark and accept rules
  for that layer

### Phase 4. Migrate Translation And Bridge Stages Off Legacy Per-Customer Programming

Goal:

- remove the biggest remaining linear rule-growth areas

Work:

- redesign muxer `DNAT` and `SNAT` programming for NAT-T and reply-path handling
- redesign or isolate NFQUEUE bridge handling so it no longer depends on the
  old per-customer rule explosion model
- decide explicitly whether head-end post-IPsec NAT remains `iptables` for now
  or also gets a new backend

Gate:

- design decision recorded for:
  - muxer translation path
  - NFQUEUE bridge path
  - head-end NAT path
- chosen backend implemented and validated

### Phase 5. Replace Shell Fan-Out With A Node-Local Apply Service Or Equivalent

Goal:

- stop using raw SSH/SCP fan-out as the normal live apply backend

Work:

- introduce a node-local apply runner, service endpoint, or pull-based bundle
  activation model
- keep rollback and validation journaled
- retain an emergency SSH path as break-glass, not as the normal scale path

Gate:

- approved live customer apply does not require the orchestrator to SCP and
  invoke multiple shell scripts as the primary control path

### Phase 6. Add Real Atomicity And Failure Containment

Goal:

- ensure partial dataplane updates do not leave inconsistent state at scale

Work:

- batch apply where the backend supports it
- introduce ordered transactions or staged activation where full atomicity is
  not possible
- improve rollback semantics for muxer plus head-end plus backend together

Gate:

- forced-failure tests prove bounded rollback behavior without orphaned customer
  state

### Phase 7. Add Real Scale Gates

Goal:

- prove the new backend is actually better, not just different

Required gates:

- 1k synthetic customer pass
- 5k synthetic customer pass
- 10k synthetic customer pass
- 20k synthetic customer pass

Metrics to record:

- rule/set/map counts
- apply latency
- remove latency
- rollback latency
- peak CPU
- peak memory
- failure recovery time

Gate:

- scale report committed to the repo with explicit pass/fail thresholds

Current status:

- complete in repo-only form
- the explicit report is committed and machine-checked
- the current report status is `failed` for `nat_t_netmap` at `1000`, `5000`,
  `10000`, and `20000`
- the failing checks are head-end apply command count, head-end rollback
  command count, and max apply commands per customer

### Phase 8. Reopen Customer Migration Only After Scale Gates Pass

Goal:

- keep migration honest

Rules:

- no claim that RPDB solved large-scale growth until Phase 7 passes
- customer-by-customer swing can continue for operational reasons only if we
  describe it honestly as:
  - improved control plane
  - not yet the final scalable dataplane backend

Gate:

- scale gates passed
- runtime backend decision closed
- customer migration statement updated to match reality

## Immediate Recommendation

The next correct engineering step is not "deploy more customers."

The next correct engineering step is:

1. freeze the current claims
2. use the explicit scale report as the current truth source
3. redesign and implement the remaining head-end post-IPsec NAT activation gap
4. only then revisit broader scale-readiness claims

Until that work is done, the repo should be treated as:

- strong customer-scoped control-plane progress
- incomplete scalable dataplane work

## Reference Documents

- [RPDB_TARGET_ARCHITECTURE.md](./RPDB_TARGET_ARCHITECTURE.md)
- [CUSTOMER_COMMAND_MODEL.md](../muxer/docs/CUSTOMER_COMMAND_MODEL.md)
- [RUNTIME_COMPLETION_PLAN.md](../muxer/docs/RUNTIME_COMPLETION_PLAN.md)
- [RUNTIME_MODE_BOUNDARIES.md](../muxer/docs/RUNTIME_MODE_BOUNDARIES.md)
- [HEADEND_CUSTOMER_ORCHESTRATION.md](./HEADEND_CUSTOMER_ORCHESTRATION.md)
- [OLD_SOLUTION_SCALETEST_50_CUSTOMER_ONBOARDING.md](./OLD_SOLUTION_SCALETEST_50_CUSTOMER_ONBOARDING.md)
