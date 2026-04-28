# Inner VPN Model

## Purpose

This document defines the inner VPN model for the CGNAT design.

The inner VPN is the customer service VPN that rides through the already
established outer certificate-authenticated tunnel. It is separate from the
outer access tunnel in identity, trust, and termination behavior.

## Core Rules

- the inner VPN is initiated by Customer Devices behind the CGNAT ISP HEAD END
- the inner VPN does not use certificates
- the inner VPN uses customer-specific keys and known inside identity
- the inner VPN is carried through the outer tunnel
- the inner VPN targets the same customer-facing public IP currently used by
  the backend VPN head-end service
- the inner VPN is steered by the CGNAT HEAD END to a backend VPN head end
- the inner VPN terminates on the backend VPN head end public loopback
- the inner VPN mode is independent from the outer tunnel mode

For the current Scenario 1 model, this means:

- the customer-facing public IP is not new
- it is the same public IP already used by the existing backend VPN head ends
- the selected backend termination loopback must match that same public IP
- the customer device is the required initiator for the inner tunnel
- the backend head end is required to respond to that initiation
- backend-initiated establishment is not required for the first demo

## Inner VPN Lifecycle

### 1. Transport Availability

The inner VPN cannot begin until the outer access tunnel exists and is usable as
transport between the CGNAT ISP HEAD END and the CGNAT HEAD END.

### 2. Customer Initiation

The Customer Device initiates the inner S2S VPN through the CGNAT ISP HEAD END.

The CGNAT ISP HEAD END acts as the path, not the service terminator.

From the customer perspective, the target remains the existing public IP used
for the backend VPN service today. CGNAT changes the path, not the
customer-facing VPN destination.

For Scenario 1, this initiation direction is part of the contract:

- customer initiates
- backend responds

### 3. Front-End Classification

The CGNAT HEAD END receives the inner VPN traffic through the outer tunnel and
classifies it for backend steering.

### 4. Backend Selection

The inner VPN is mapped to the selected backend VPN head end or backend class
using framework rules, operations inventory, and SoT intent.

### 5. Backend Termination

The backend VPN head end presents the public loopback identity and terminates
the inner VPN.

That preserves the current customer-facing termination identity even though the
packet path now flows:

- through the CGNAT ISP HEAD END
- into the CGNAT HEAD END
- across GRE to the backend head end

### 6. Post-Termination Service Path

After inner VPN termination, traffic either:

- continues without translation, or
- is translated from customer-original inside space to platform-assigned inside
  space

## Scenario Patterns

### Scenario 1: 1:1 Outer-to-Inner Relationship

In Scenario 1:

- one customer device forms the outer tunnel
- that same customer context forms one inner tunnel
- the outer tunnel is expected to be NAT-T
- the inner tunnel may still remain non-NAT-T
- the customer device is the required initiator for the inner tunnel
- the backend head end is the required responder for the first demo

This is the important design point:

- outer NAT-T does not force inner NAT-T

The current framework should support this as the first implementation target.

### Scenario 2: n:1 Outer-to-Inner Relationship

In Scenario 2:

- one ISP/interconnect-owned outer tunnel carries many inner customer tunnels
- each inner tunnel still targets the existing customer-facing public IP
- each inner tunnel still needs its own backend selection and service identity

This means the CGNAT HEAD END must eventually support:

- aggregation at the outer layer
- separation at the inner service layer

Scenario 2 is planned, but it is more complex than Scenario 1 because one
outer access context carries multiple service tunnels.

## Identity Model

The inner VPN identity is distinct from the outer tunnel identity.

It is based on:

- customer-specific key material
- known inside customer identity
- SoT-owned customer/service intent

The outer certificate identity must never be treated as a substitute for the
inner service identity.

## Termination Model

The backend VPN head end owns service termination for the inner VPN.

This means the backend tier is responsible for:

- presenting the public loopback identity
- accepting the inner VPN
- applying any required address translation
- enforcing service-side routing boundaries

## Framework, Operations, and SoT Ownership

### Framework-Owned

- inner VPN role separation
- steering and termination expectations
- config and validation shapes

### Operations-Owned

- environment-specific backend inventory
- concrete public loopback values
- the current customer-facing public IP value used for the service
- deployment-time certificate and key references

### SoT-Owned

- customer/service intent
- known inside customer identity
- backend class or backend selection intent
- address assignment intent

## Validation Expectations

The first working version should prove:

- the inner VPN can traverse the outer tunnel
- the CGNAT HEAD END can steer the inner VPN correctly
- the backend VPN head end can terminate the inner VPN on the public loopback
- the customer can initiate the inner VPN successfully
- the backend responds and return traffic follows the intended reverse path
- the return path remains correct

## Acceptance Criteria

This document is complete enough for the current phase when:

- the inner VPN role is clearly separated from the outer tunnel
- the no-certificates rule for the inner VPN is explicit
- the backend termination responsibility is explicit
- the framework/operations/SoT split is explicit
