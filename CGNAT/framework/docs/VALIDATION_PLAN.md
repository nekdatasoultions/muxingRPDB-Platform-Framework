# Validation Plan

## Purpose

This document defines how the CGNAT framework should be validated before the
infrastructure test deployment Go / No-Go decision and before any first working
version claim.

## Validation Layers

### Layer 1: Contract Validation

Validate that the framework, operations, and SoT inputs are structurally
complete and consistent.

This includes:

- required top-level sections exist
- placement constraints are respected
- required identity and addressing intent is present
- backend inventory is available

### Layer 2: Render Validation

Validate that a CGNAT deployment bundle can be rendered into deployable shapes.

This includes:

- deployment summary
- topology summary
- Go / No-Go checklist data

### Layer 3: Topology Validation

Validate that the configured topology matches the approved design.

This includes:

- one CGNAT HEAD END in `subnet-04a6b7f3a3855d438`
- one CGNAT ISP HEAD END spanning the approved subnet set
- Customer Devices only in `subnet-0e6ae1d598e08d002`
- backend inventory exists for NAT-T or non-NAT service classes

### Layer 4: Functional Validation

Validate the design behavior itself.

This includes:

- outer certificate-authenticated tunnel behavior
- inner VPN transport through the outer tunnel
- GRE steering to backend VPN head ends
- public loopback termination
- optional translation to platform-assigned space
- reverse-path correctness

## Scenario 1 Inner-Tunnel Role Validation

For Scenario 1, validation must explicitly prove:

- the customer device can initiate the inner VPN
- the backend head end responds to that initiation
- backend-initiated establishment is not required for the first demo

This means the first demo pass/fail criteria are based on successful
customer-initiated establishment, not on symmetric initiation support.

## Scenario 1 Reverse-Path Verification Procedure

For Scenario 1, reverse-path correctness must be validated with an explicit
procedure instead of a generic statement.

### Required Procedure

1. establish the outer tunnel from the customer device to the CGNAT HEAD END
2. establish the inner VPN from the customer device to the existing backend VPN
   public service IP
3. send test traffic from the customer side across the inner VPN
4. verify request-path traversal at:
   - customer-side tunnel state
   - CGNAT HEAD END outer-tunnel side
   - CGNAT HEAD END GRE side
   - selected backend head end
5. generate reply traffic from the backend side
6. verify return-path traversal at:
   - selected backend head end
   - CGNAT HEAD END GRE side
   - CGNAT HEAD END outer-tunnel side
   - customer side
7. confirm that return traffic follows the intended CGNAT path and does not
   bypass the CGNAT HEAD END or GRE handoff

### Accepted Evidence

Accepted proof may be any combination of:

- packet captures
- interface counters
- tunnel state output
- successful request/reply test results

### Minimum Required Evidence

The minimum Scenario 1 evidence set should include:

- successful inner VPN establishment
- successful end-to-end request and reply
- visible request and reply on:
  - the CGNAT HEAD END outer-tunnel path
  - the CGNAT HEAD END GRE path
  - the selected backend head end

## Required Checks for the First Working Version

### Input Checks

- framework section exists
- operations section exists
- sot section exists
- outer tunnel auth method is `certificate`
- inner VPN auth method is `key_based`
- handoff transport is `gre`

### Placement Checks

- CGNAT HEAD END subnet is allowed
- CGNAT ISP HEAD END transit subnet is allowed
- CGNAT ISP HEAD END customer subnet is allowed
- Customer Device subnet placement is allowed

### Inventory Checks

- at least one backend VPN head end is defined
- the selected backend class exists in operations inventory
- the selected public loopback exists in backend inventory

### Addressing Checks

- customer-original inside space is present
- platform-assigned inside space is present when translation is enabled
- translation mode is recognized

### Ownership Checks

- framework values describe behavior, not one-off environment state
- operations values describe deployment context
- SoT values describe service intent and inventory relationships

### Scenario 1 Behavioral Checks

- the inner VPN initiator is the customer device
- the backend head end is operating as responder for the first demo
- the customer-facing public IP matches the selected termination public
  loopback
- reverse-path evidence shows request and reply traversing both the outer
  tunnel path and the GRE handoff path

## Go / No-Go Support

Validation must produce enough information to answer the Go / No-Go questions
without hidden manual assumptions.

At minimum the validation output must support:

- whether the bundle is structurally complete
- whether placement is acceptable
- whether backend inventory is sufficient
- whether translation intent is complete
- whether the deployment shape can be rendered cleanly

## Minimum Deliverables

The validation toolchain should produce:

- a machine-readable validation result
- a rendered deployment summary
- a rendered Go / No-Go checklist

## Acceptance Criteria

This document is complete enough for the current phase when:

- the validation layers are explicit
- the first working version checks are explicit
- the Go / No-Go relationship is explicit
- the expected validation outputs are explicit
