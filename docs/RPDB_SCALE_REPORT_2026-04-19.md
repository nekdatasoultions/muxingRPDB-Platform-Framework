# RPDB Scale Report 2026-04-19

## Scope

This report captures the current repo-only scale result for RPDB.

It covers:

- code and docs inside this repository only
- no AWS access
- no node access
- no customer deployment
- no `MUXER3` changes

## Evidence Sources

- `build/scale-baseline/phase7-metrics.json`
- `build/scale-baseline/phase7-report.json`
- `build/scale-baseline/phase7-report.md`
- `muxer/config/scale-thresholds.json`
- `build/repo-verification/repo-verification-summary.json`

## Summary

The explicit repo-only scale gate now exists and is machine-checked.

Current result:

- muxer-side classification, translation, and bridge measurements pass the
  current explicit thresholds
- the explicit report overall status is `failed`
- the only failing profile is `nat_t_netmap`
- the failing counts are `1000`, `5000`, `10000`, and `20000`
- the failing checks are:
  - `headend_apply_commands`
  - `headend_rollback_commands`
  - `headend_max_apply_per_customer`

This means the current remaining scale blocker is not the muxer pass-through
classification backend.

It is the head-end post-IPsec NAT activation model for translated NAT-T
customers.

## Measured Failure Details

### `nat_t_netmap` at `1000`

- apply commands: `4000`
- rollback commands: `3000`
- max apply commands per customer: `4`
- threshold intent:
  - apply commands: at most `2 x customer_count`
  - rollback commands: at most `2 x customer_count`
  - max apply commands per customer: `2`

### `nat_t_netmap` at `5000`

- apply commands: `20000`
- rollback commands: `15000`
- max apply commands per customer: `4`
- threshold intent:
  - apply commands: at most `2 x customer_count`
  - rollback commands: at most `2 x customer_count`
  - max apply commands per customer: `2`

### `nat_t_netmap` at `10000`

- apply commands: `40000`
- rollback commands: `30000`
- max apply commands per customer: `4`
- threshold intent:
  - apply commands: at most `2 x customer_count`
  - rollback commands: at most `2 x customer_count`
  - max apply commands per customer: `2`

### `nat_t_netmap` at `20000`

- apply commands: `80000`
- rollback commands: `60000`
- max apply commands per customer: `4`
- threshold intent:
  - apply commands: at most `2 x customer_count`
  - rollback commands: at most `2 x customer_count`
  - max apply commands per customer: `2`

## What Passed

The current repo-only evidence shows that these areas are no longer the primary
scale blocker:

- pass-through classification backend selection
- muxer-side legacy rule growth for the measured synthetic profiles
- muxer translation path under the active repo-modeled backend
- bridge-specific synthetic profiles under the active repo-modeled backend
- plan-build timing, CPU, and peak memory thresholds for the measured profiles

## What Is Still Open

The remaining blocker is the head-end post-IPsec NAT activation shape for
translated NAT-T customers.

Today, that layer still expands as linear command growth:

- `4` apply commands per customer
- `3` rollback commands per customer

That is why the explicit report remains `failed`.

## Honest Deployment Readiness Statement

The current repo-only scale result is:

- improved control plane
- improved muxer-side dataplane modeling
- explicit measured scale evidence
- not yet a deployment go for the translated NAT-T head-end activation path

## Stop Point

This report does not authorize:

- AWS actions
- node rollout
- customer apply
- `MUXER3` changes

The next real engineering task is to reduce or redesign the `nat_t_netmap`
head-end activation path, then rerun the explicit scale gate.
