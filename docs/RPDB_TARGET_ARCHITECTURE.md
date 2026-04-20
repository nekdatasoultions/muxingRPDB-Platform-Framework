# RPDB Target Architecture

## Purpose

This document captures the target model for the RPDB-based muxing platform.

The current platform works, but the present control-plane shape will get
painful at larger scale because it still leans on:

- monolithic customer authoring
- full-fleet render/apply behavior
- one-customer-at-a-time shell command fan-out
- implicit RPDB rule priorities
- large linear iptables growth

This repo is the clean place to fix those concerns without disturbing the
currently deployed framework.

## Target Model

The target model has four main properties:

1. One customer source file per customer
2. One canonical merged DynamoDB item per customer
3. Per-customer sync, render, and apply by default
4. Explicit RPDB and fwmark design on the muxer

## Control Plane

### Repo Authoring

Each customer should have its own source file under a modular customer tree.

Shared defaults should stay separate from customer records so customer files
can stay small and readable.

### Canonical SoT

DynamoDB remains the runtime customer source of truth, but it should be used
as one item per customer, not as a table that is fully scanned for every
normal operation.

### Render and Apply

The default workflows should become:

- sync one customer
- render one customer
- validate one customer
- apply one customer

Fleet-wide actions should still exist, but they should be explicit, not the
default for routine onboarding and maintenance.

## Dataplane

### RPDB

The muxer should keep fwmark-based routing policy.

The difference in the new model is that rule priorities should be explicit and
reserved from the start, instead of relying on kernel-assigned priorities.

### Steering

The intended steering pattern stays:

- classify packet
- set fwmark
- RPDB rule matches fwmark
- route lookup sends traffic into the customer transport path

### Rule Programming

The new model should move away from large numbers of individual shell command
insertions when programming dataplane state.

Better targets:

- batch updates
- atomic application where possible
- eventual nftables set and map usage instead of very large linear rule lists

## Migration Boundary

This repo should not change live nodes until:

- the new customer source model is stable
- RPDB priority design is documented
- the new render and apply flow is implemented
- rollback expectations are written down
