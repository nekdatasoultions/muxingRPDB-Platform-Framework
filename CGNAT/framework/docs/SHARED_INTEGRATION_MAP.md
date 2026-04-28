# Backend Contract Map

## Purpose

This document defines how the CGNAT framework relates to the existing backend
platform without changing muxer-owned code or schemas.

The hard rule for the current design is:

- CGNAT is net new
- muxer is not touched
- existing backend VPN head ends are treated as external contract targets

That means this document is no longer a plan to extend shared RPDB surfaces.
It is now a map of:

- what CGNAT owns
- what the existing backend is assumed to already provide
- where the handoff contract lives
- how the shared SoT database can be used without changing muxer-owned shapes

## Core Position

CGNAT should be treated as:

- a net-new ingress framework
- a net-new operations model
- a new access path into the current backend platform
- a consumer of an existing backend contract

CGNAT should not be treated as:

- a muxer schema extension
- a muxer runtime extension
- a new implementation branch inside the current backend
- a replacement for the existing backend platform

## End-to-End Responsibility Split

### CGNAT Owns

CGNAT owns:

- the CGNAT HEAD END design
- the CGNAT ISP HEAD END design
- outer tunnel behavior
- ingress-side control plane
- ingress-side operations model
- CGNAT-specific SoT record shapes
- AWS placement and deployment shapes for CGNAT infrastructure
- GRE handoff behavior from CGNAT HEAD END to backend head ends
- validation and Go / No-Go tooling for CGNAT

### Existing Backend Owns

The current backend platform continues to own:

- NAT-T and non-NAT backend VPN head ends
- public loopback identities
- inner VPN termination
- backend routing behavior
- backend-side address translation behavior where required
- current muxer implementation details

### Shared Boundary

The shared boundary is the handoff from:

- `CGNAT HEAD END`

to:

- existing backend VPN head ends

That handoff must be treated as an external contract, not as an invitation to
change muxer internals.

## Backend Contract Assumptions

For the current project block, CGNAT assumes the existing backend already
provides:

- NAT-T and non-NAT backend head-end pools
- GRE-reachable backend endpoints
- public loopback identities for service termination
- current backend-side service routing and return-path behavior
- backend-side inner VPN termination behavior

CGNAT must therefore supply:

- a valid outer access path
- a valid inner VPN ingress path
- deterministic steering to the chosen backend target
- any ingress-side metadata needed to choose the correct backend path
- preservation of the existing customer-facing public service IP as the inner
  VPN target

## Contract Layers

### 1. Transport Contract

CGNAT must know:

- which backend endpoint(s) are reachable over GRE
- what addressing and interface assumptions apply to that GRE handoff
- what the backend expects to receive at the GRE boundary

The backend is assumed to remain unchanged.

### 2. Termination Contract

CGNAT must know:

- which public loopback identity the customer-facing service should ultimately
  terminate on
- that the customer should keep pointing the inner S2S VPN at the same public
  IP currently used on the muxer-backed service path
- whether the service is intended for the NAT-T or non-NAT backend tier

The backend is assumed to preserve its current termination logic.

This means the path changes but the customer-facing target does not:

- customer points at the existing public service IP
- traffic traverses the CGNAT ISP HEAD END
- reaches the CGNAT HEAD END
- is carried across GRE to the selected backend head end
- terminates on the existing backend public loopback/public IP behavior

### 3. Translation Contract

CGNAT must know whether translation is expected after backend termination, but
it does not move that responsibility into muxer changes.

For the current design:

- CGNAT may carry translation intent
- the existing backend remains the translation boundary unless a later design
  explicitly proves otherwise

### 4. Operational Contract

CGNAT operations must know:

- where CGNAT HEAD END infrastructure is deployed
- where CGNAT ISP HEAD END infrastructure is deployed
- how those nodes reach the existing backend

The backend deployment model remains external to CGNAT for now.

## SoT Database Position

CGNAT may use the same SoT database platform or database instance family as the
current platform, but it should not rely on muxer-owned schemas or item shapes
for its first implementation.

The safer starting rule is:

- shared storage is acceptable
- shared muxer-owned record shapes are not assumed

In practice that means CGNAT should plan for:

- CGNAT-owned records
- CGNAT-owned namespaces, item families, or prefixes
- CGNAT-owned validation rules

while still allowing a later decision to align storage layout more closely if
that becomes useful.

## What Stays Inside CGNAT

The following stays inside `CGNAT/`:

- CGNAT framework docs
- CGNAT operations docs
- CGNAT SoT contracts
- CGNAT infra deployable shapes
- CGNAT server-side renderable shapes
- CGNAT bundle, validation, and render tooling
- backend contract documentation for CGNAT consumption

## What Is Explicitly Out of Scope

The following are out of scope for the current project block:

- editing muxer schemas
- editing muxer runtime code
- editing muxer provisioning code
- editing backend live apply logic
- changing current backend head-end behavior

If later work suggests any of those are required, that is a separate stop point
and approval decision.

## Recommended Implementation Order

### Stage 1: Backend Contract Definition

Define:

- GRE handoff expectations
- backend target selection model
- public loopback termination expectations
- translation expectations

Outcome:

- CGNAT has a stable backend-facing contract target

### Stage 2: CGNAT-Owned SoT Contract

Define:

- CGNAT service identity shape
- CGNAT ingress identity shape
- backend selection intent shape
- translation intent shape

Outcome:

- CGNAT has its own input model without touching muxer-owned schemas

### Stage 3: CGNAT Deployable Shapes

Define and render:

- AWS infrastructure deployables
- server-side deployables
- validation artifacts

Outcome:

- CGNAT can be deployed and tested as a net-new ingress framework

### Stage 4: Go / No-Go for Test Infrastructure

Review:

- backend contract clarity
- SoT contract clarity
- infra shapes
- server-side shapes
- rollback assumptions

Outcome:

- explicit decision on whether to deploy test infrastructure

## Current Stop Point

We are currently before any work outside `CGNAT/`.

No muxer files should be touched as part of the current plan.

If someone later proposes:

- muxer schema edits
- muxer runtime edits
- backend live apply edits

that is a separate design change and requires a new explicit approval step.

## Summary

The clean working model is:

- CGNAT is net new
- the current backend is unchanged
- the backend is an external contract target
- CGNAT may share the SoT database platform, but not muxer-owned shapes by
  default
- all current work stays inside `CGNAT/`
