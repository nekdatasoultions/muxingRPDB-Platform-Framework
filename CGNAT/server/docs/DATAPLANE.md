# Dataplane

## Purpose

This document defines the intended dataplane behavior for the CGNAT design.

The dataplane described here is still framework-level design. It explains how
traffic should move between the CGNAT ISP HEAD END, the CGNAT HEAD END, and the
backend VPN head ends without tying the design to a single AWS environment.

## Dataplane Objective

The dataplane must support this sequence:

1. The CGNAT ISP HEAD END establishes the outer certificate-authenticated
   tunnel to the CGNAT HEAD END.
2. Customer Devices send the inner S2S VPN through that outer tunnel.
3. The CGNAT HEAD END classifies the inner VPN flow.
4. The CGNAT HEAD END steers the inner VPN over GRE to the selected backend VPN
   head end.
5. The backend VPN head end presents the public loopback identity, terminates
   the inner VPN, and performs optional address translation.
6. Return traffic follows the reverse path predictably.

## Dataplane Stages

### Stage 1: Outer-Tunnel Ingress

Ingress begins at the CGNAT HEAD END once the outer tunnel is established.

At this stage, the dataplane must:

- treat the outer tunnel as the trusted transport boundary
- accept traffic only after successful outer-tunnel authentication
- expose the carried inner VPN traffic to the CGNAT HEAD END logic

### Stage 2: Inner-VPN Classification

The CGNAT HEAD END must classify the inner VPN traffic so it can be steered to
the correct backend VPN head end or head-end class.

The classification model should be able to work from structured inputs such as:

- service identity from SoT
- framework steering rules
- operations/environment target inventory

At this phase we are not locking down the final matching implementation, only
the responsibility boundary.

### Stage 3: GRE Handoff

The CGNAT HEAD END is expected to steer the inner VPN over GRE to backend VPN
head ends.

The GRE handoff model should:

- preserve enough packet context for the backend to terminate the inner VPN
- avoid blurring the role of the CGNAT HEAD END and the backend VPN head end
- be driven by variable/config inputs rather than fixed endpoint assumptions

### Stage 4: Backend VPN Termination

The backend VPN head end must:

- receive the steered inner VPN flow
- present the public loopback identity
- terminate the inner S2S VPN
- decide whether address translation is required

This preserves the current RPDB idea that service termination belongs on the
backend VPN head-end tier rather than the front access tier.

### Stage 5: Service-Side Forwarding

After inner VPN termination, service-side traffic must:

- route toward the intended platform-side services or destinations
- optionally traverse address translation from customer-original inside space
  to platform-assigned inside space
- maintain deterministic reverse-path behavior

## Role of Each Dataplane Component

### CGNAT ISP HEAD END

Dataplane responsibilities:

- carry downstream inner VPN traffic through the outer tunnel
- forward, not terminate, the inner VPN service intent

### CGNAT HEAD END

Dataplane responsibilities:

- receive traffic from the outer tunnel
- classify inner VPN traffic
- steer that traffic over GRE to the appropriate backend

### Backend VPN Head End

Dataplane responsibilities:

- receive steered GRE traffic
- terminate the inner VPN on the public loopback identity
- perform any required address translation
- route return traffic back toward the CGNAT HEAD END

## Return-Path Model

The return path must remain explicit and symmetric.

That means:

1. reply traffic leaves the service-side destination
2. if translation was applied, reverse translation happens at the backend VPN
   head end
3. the backend VPN head end returns the traffic through the same service
   termination context
4. the traffic is sent back to the CGNAT HEAD END over the GRE path
5. the CGNAT HEAD END sends it back through the outer tunnel to the CGNAT ISP
   HEAD END
6. the CGNAT ISP HEAD END returns it to the Customer Device

The design should avoid any hidden routing dependency that causes the reply path
to bypass the backend VPN head end or the CGNAT HEAD END.

## Placement and Variable Requirements

The dataplane must respect the approved placement model:

- CGNAT HEAD END only in `subnet-04a6b7f3a3855d438`
- CGNAT ISP HEAD END in:
  - `subnet-04a6b7f3a3855d438`
  - `subnet-0e6ae1d598e08d002`
- Customer Devices only in `subnet-0e6ae1d598e08d002`

All dataplane-relevant values must be variable-driven, including:

- interface placement
- GRE endpoints
- public loopback values
- backend target inventory
- inside address mappings

## Framework, Operations, and SoT Ownership

### Framework-Owned

- dataplane stage definitions
- role boundaries
- expected GRE steering model
- validation rules for rendered dataplane intent

### Operations-Owned

- actual AWS subnet and interface bindings
- concrete GRE endpoint values
- reachable backend VPN head-end inventory in a given environment

### SoT-Owned

- customer/service identity used by steering
- backend selection intent
- address-assignment intent consumed by translation and service routing

## Open Design Questions

- What exact packet features will drive final inner-VPN classification?
- How should backend class selection be represented in config and SoT?
- What minimum observability do we need at the CGNAT HEAD END to confirm
  correct steering?
- What is the best way to validate return-path symmetry in the first prototype?

## Acceptance Criteria

This document is complete enough for the current phase when:

- the dataplane stages are explicit
- the GRE handoff responsibility is explicit
- the backend VPN termination responsibility is explicit
- the return path is explicit
- the framework/operations/SoT ownership split is clear
