# Migration Plan

## Scope

This document tracks the migration from the current framework to the RPDB
platform model.

## Phase 0

Create the new repo and scaffold the new layout.

Status:

- complete

## Phase 1

Define the source-of-truth model.

Deliverables:

- per-customer source layout
- shared defaults layout
- example NAT customer source
- example strict non-NAT customer source
- documented DynamoDB item shape

## Phase 2

Define the RPDB steering model.

Deliverables:

- explicit RPDB priority plan
- fwmark reservation plan
- route-table allocation plan
- muxer dataplane notes

## Phase 3

Refactor the render and sync path.

Deliverables:

- sync one customer
- render one customer
- render fleet intentionally
- remove normal-operation dependence on full-table DynamoDB scans

## Phase 4

Refactor the muxer apply path.

Deliverables:

- per-customer apply
- per-customer rollback
- reduced shell command fan-out
- measured apply timing

## Phase 5

Validate against the lab estate.

Deliverables:

- one-customer validation
- measured RPDB growth
- measured route growth
- measured ruleset growth
- rollback confirmation

## Phase 6

Plan controlled production adoption.

Deliverables:

- production readiness checklist
- live node backup gate
- migration runbook
- customer cutover sequence

## Deployment Baseline

Before any RPDB live-node work, a shared backup baseline already exists from
April 13, 2026. The deployment branch should treat that backup-first workflow as
mandatory, not optional.
