# RPDB Scale Pre-Deploy Review Package 2026-04-19

## Purpose

This package is the final repo-only review checkpoint for the RPDB scale work.

It is meant to answer:

- what changed
- what was proven
- what is still open
- whether deployment should proceed

## Scope

This package is repo-only.

It includes:

- code changes
- repo verification
- synthetic scale evidence
- design and failure-containment notes

It excludes:

- AWS changes
- node rollout
- customer apply
- `MUXER3` changes

## What Changed

The repo now contains:

- a real pass-through `nftables` classification backend in the repo-modeled
  apply path
- explicit translation and bridge scale decisions
- repo-only measurement for strict non-NAT, NAT-T, translated NAT-T, mixed, and
  bridge-focused synthetic profiles
- staged activation-bundle journaling and rollback verification for the current
  customer apply model
- explicit scale thresholds and a machine-checked pass/fail report

## What Was Proven Repo-Only

The repo verification suite now proves:

- customer-scoped runtime commands stay on the strict DynamoDB customer lookup
  boundary
- the repo-modeled pass-through backend selects `nftables`
- muxer-side translation and bridge behavior are measured separately from the
  old legacy baseline
- staged activation-bundle apply and rollback journals are generated
- forced-failure staged apply leaves bounded rollback artifacts instead of
  orphaned staged customer state
- the explicit scale report is generated from measured data and says pass or
  fail without interpretation drift

## Gate Failures Found And Fixed During This Execution Block

The repo-only verification work found and corrected these issues:

1. Activation bundle copy failed when deep nested destination parents did not
   exist.
2. Windows path length growth broke the watcher-triggered staged apply path.
3. Short target slugs caused active and standby activation bundles to collide.

Those fixes were integrated before the final verification reruns.

## Current Scale Result

Current explicit result:

- overall report status: `failed`
- only failing profile: `nat_t_netmap`
- failing counts: `1000`, `5000`, `10000`, `20000`
- failing checks:
  - `headend_apply_commands`
  - `headend_rollback_commands`
  - `headend_max_apply_per_customer`

Current interpretation:

- the muxer-side pass-through backend is no longer the primary blocker
- the remaining blocker is head-end post-IPsec NAT activation growth for
  translated NAT-T customers

## What Still Requires Live Validation Even After The Repo Work

Even after the repo-only work, live validation would still be required for:

- node-local activation behavior on real RPDB nodes
- operational latency on real hardware
- observability and rollback timing on real nodes
- customer-path validation in both directions

Those live checks are outside the allowed scope of this review package.

## Deployment Recommendation

Current recommendation: `no-go`

Why:

- the explicit scale report is still red for the translated NAT-T head-end
  activation path
- deploying now would skip the one remaining blocker the repo can already see
- that would repeat the exact kind of fictitious completion state we were
  trying to eliminate

## Required Next Engineering Task

Before deployment review should reopen, the repo needs one of these:

- a batched or otherwise reduced head-end post-IPsec NAT activation backend for
  `nat_t_netmap`
- or an explicitly accepted architectural change with thresholds rewritten to
  match the accepted transitional model

After that:

1. rerun the scale harness
2. rerun the explicit scale report
3. rerun the full repo verification suite
4. only reopen deployment review if the result is green for the accepted target

## Stop Point

This package is the stop point for this execution block.

Do not:

- deploy code
- touch AWS
- touch nodes
- apply a customer
- modify `MUXER3`
