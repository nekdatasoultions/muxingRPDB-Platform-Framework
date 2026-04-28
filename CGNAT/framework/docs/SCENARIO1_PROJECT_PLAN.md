# Scenario 1 Project Plan

## Purpose

This document defines the first implementation target for CGNAT: Scenario 1.

Scenario 1 is the simplest deployable model and the correct first proving
ground for the CGNAT framework.

## Scenario 1 Definition

Scenario 1 assumes:

- a single customer device is behind an ISP using CGN
- the customer-side device is also the logical CGNAT ISP-side endpoint
- there is a 1:1 relationship between the outer tunnel and the inner tunnel
- the outer tunnel is between the customer device and the CGNAT HEAD END public
  IP
- the inner tunnel is between a customer loopback and the existing standard
  backend service public IP

## Core Technical Rules

### Outer Tunnel

- initiated by the customer device
- always certificate-authenticated
- current demo target is `IKEv2`
- expected to run in `NAT-T`
- terminates on the CGNAT HEAD END public IP

### Inner Tunnel

- targets the same customer-facing public IP already used by the current
  backend service
- uses keys, not certificates
- for Scenario 1, must be initiated by the customer device
- for Scenario 1, the backend head end is required to respond to that
  initiation
- backend-initiated establishment is optional future behavior and is not
  required for the first demo
- may remain non-NAT-T even when the outer tunnel is NAT-T

### Customer Loopback Identity

- for the Scenario 1 demo, the customer loopback identity should use `10.x`
  space
- that loopback must not overlap with platform-assigned inside space
- that loopback must be treated as a variable-driven input, not a hardcoded
  permanent address rule

### Production Direction for Loopback Identity

Production should assume:

- the loopback identity remains variable-driven
- the address may be any valid customer-provided loopback identity
- overlap validation remains mandatory

### Backend Path

- CGNAT HEAD END receives the inner tunnel through the outer tunnel
- CGNAT HEAD END forwards the inner tunnel across GRE to the selected backend
  head end
- backend head end preserves the current public loopback/public service
  identity

### GRE Endpoint Allocation

- for the Scenario 1 demo, GRE endpoint allocation should use the existing
  shared GRE address space that is already defined for the platform
- CGNAT should consume the next available GRE endpoint assignment from that
  existing space
- CGNAT should not introduce a new standalone GRE address pool for Scenario 1

### Production Direction for GRE Allocation

Production should assume:

- GRE endpoint allocation remains variable-driven
- the allocation source is still an operations-owned inventory reference
- allocation policy may evolve, but reuse of the existing shared GRE space is
  the starting model

## Demo PKI Decision

For Scenario 1, the outer certificate model is defined as follows:

- the CGNAT HEAD END will run a local certificate authority for demo and test
  purposes
- customer-side outer tunnel certificates will be issued by that local CA
- the local CA model is a demo implementation choice, not the production trust
  model

### Production Direction

Production should assume:

- the local CA is replaced by a third-party or enterprise CA
- certificate issuance is externalized
- trust anchor lifecycle is handled outside the demo-only CGNAT HEAD END CA

### What This Resolves

This means the previous blocker:

- "exact outer certificate model not defined"

is no longer an open blocker for Scenario 1.

It is now replaced by a concrete assumption:

- "demo PKI uses a local CA on the CGNAT HEAD END"

## Demo Loopback Identity Decision

For Scenario 1, the customer loopback identity model is defined as follows:

- use a non-overlapping `10.x` loopback address for demo
- keep that loopback as a variable-driven SoT input
- do not treat `10.x` as the permanent production-only rule

### What This Resolves

This means the previous blocker:

- "exact customer loopback/service identity not frozen"

is no longer an open blocker for Scenario 1.

It is now replaced by a concrete assumption:

- "Scenario 1 demo loopback uses non-overlapping `10.x` space, but remains
  variable-driven for production"

## GRE Inventory Decision

For Scenario 1, the GRE endpoint inventory model is defined as follows:

- use the existing shared GRE space already defined for the platform
- allocate the next available GRE endpoint assignment from that space
- keep the inventory source and allocation policy in operations-owned inputs

### What This Resolves

This means the previous blocker:

- "exact GRE endpoint inventory not frozen"

is no longer an open blocker for Scenario 1.

It is now replaced by a concrete assumption:

- "Scenario 1 GRE endpoint allocation uses the existing shared GRE space and
  takes the next available assignment"

## Backend Public Target Decision

For Scenario 1, the backend public target model is defined as follows:

- the customer-facing inner VPN target must be the same existing public IP
  already used by the current backend VPN head ends
- the backend termination loopback must match that same public IP for the
  selected backend service target
- CGNAT must not introduce a new customer-facing inner VPN public IP for
  Scenario 1

### What This Resolves

This means the previous blocker:

- "exact backend public IP / loopback target not frozen"

is no longer an open blocker for Scenario 1.

It is now replaced by a concrete assumption:

- "Scenario 1 reuses the existing backend VPN public service IP, and the
  customer-facing target must match the selected termination public loopback"

## Inner Tunnel Initiation Decision

For Scenario 1, the inner tunnel initiator/responder model is defined as
follows:

- the customer device is the required initiator for the inner tunnel
- the backend head end is required to respond to that customer-initiated inner
  tunnel
- backend-initiated tunnel establishment is not required for the first demo

### What This Resolves

This means the previous blocker:

- "inner tunnel initiator/responder expectations not frozen"

is no longer an open blocker for Scenario 1.

It is now replaced by a concrete assumption:

- "Scenario 1 requires customer-initiated inner VPN establishment with backend
  responder behavior"

## Reverse-Path Verification Decision

For Scenario 1, the reverse-path verification procedure is defined as follows:

1. establish the outer tunnel from the customer device to the CGNAT HEAD END
2. establish the inner VPN from the customer device to the existing backend VPN
   public service IP
3. send test traffic from the customer side across the inner VPN
4. verify request-path visibility at:
   - the customer-side tunnel state
   - the CGNAT HEAD END outer-tunnel side
   - the CGNAT HEAD END GRE handoff side
   - the selected backend head end
5. generate reply traffic from the backend side
6. verify return-path visibility at:
   - the selected backend head end
   - the CGNAT HEAD END GRE handoff side
   - the CGNAT HEAD END outer-tunnel side
   - the customer side
7. verify the return traffic follows the same intended transport path back and
   does not bypass the CGNAT path

### Minimum Evidence

At minimum, the Scenario 1 review package should include:

- successful inner tunnel establishment state
- successful test request and reply
- packet capture, interface counters, or equivalent proof on:
  - CGNAT HEAD END outer-tunnel path
  - CGNAT HEAD END GRE path
  - selected backend head end

### What This Resolves

This means the previous blocker:

- "reverse-path verification procedure not frozen"

is no longer an open blocker for Scenario 1.

It is now replaced by a concrete assumption:

- "Scenario 1 reverse-path proof requires visible request and reply traversal
  across both the outer tunnel path and the GRE handoff path"

## Success Criteria

Scenario 1 is considered successful when:

1. the customer device establishes the outer certificate-authenticated NAT-T
   tunnel to the CGNAT HEAD END public IP
2. the customer device establishes the inner S2S VPN to the existing
   customer-facing public IP
3. the CGNAT HEAD END receives that inner VPN through the outer tunnel
4. the CGNAT HEAD END forwards it across GRE to the selected backend head end
5. the backend head end preserves the current public loopback/public service
   identity
6. return traffic follows the reverse path correctly

## Phases

### Phase 1: Freeze the Scenario 1 Contract

Define and freeze:

- customer-side collapsed 1:1 model
- outer tunnel behavior
- inner tunnel behavior
- backend handoff behavior
- backend public IP/public loopback target

### Phase 2: Freeze the Demo PKI Model

Define and freeze:

- local CA location on the CGNAT HEAD END
- certificate issuance assumptions for customer-side outer tunnels
- trust anchor distribution assumptions for demo use

### Phase 3: Freeze the SoT Shape

Define the minimum Scenario 1 SoT shape for:

- service identity
- outer tunnel identity
- customer loopback identity
- backend class
- customer-facing public IP
- backend termination loopback
- translation intent

### Phase 4: Freeze the Backend Contract

Define:

- customer-facing public IP target
- backend class selection
- GRE remote target
- public loopback termination behavior

### Phase 5: Freeze the Server-Side Shapes

Define:

- outer tunnel termination shape
- GRE handoff shape
- backend contract render shape
- validation expectations

### Phase 6: Infrastructure Test Go / No-Go

Before any test deployment:

- outer tunnel model must be explicit
- demo PKI model must be explicit
- SoT record shape must be explicit
- backend contract must be explicit
- rollback expectations must be explicit

### Phase 7: Controlled Test Deployment

Deploy:

- one CGNAT HEAD END
- one Scenario 1 customer-side endpoint
- backend connectivity over GRE

### Phase 8: Validation

Validate:

- outer tunnel up
- cert trust working
- inner tunnel up
- customer device initiated the inner tunnel successfully
- backend head end responded successfully
- same customer-facing public IP preserved
- GRE handoff working
- backend loopback termination working
- reverse path working

## Hard Blockers

At this point, the original Scenario 1 blockers addressed in this document have
been converted into concrete assumptions or rules for the first demo.

The remaining gating items are implementation and test-execution tasks, not
unfrozen design blockers in the Scenario 1 contract itself.

## Out of Scope

Scenario 1 does not attempt to solve:

- shared n:1 outer tunnels
- provider-owned interconnect gateways
- outer tunnel protocol matrix beyond the initial demo target
- production CA lifecycle
- muxer code or schema changes

## Summary

Scenario 1 is now the fixed first implementation target.

Its trust model for demo is:

- local CA on the CGNAT HEAD END

Its customer-facing rule remains:

- same public IP target as today

Its path rule remains:

- customer device
- outer tunnel
- CGNAT HEAD END
- GRE
- backend head end
