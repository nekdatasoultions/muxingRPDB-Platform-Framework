# CGNAT Project Plan

## 1. Purpose

Create a dedicated `CGNAT/` workspace under the RPDB repo to design,
prototype, and validate a net-new CGNAT access architecture that hands traffic
off to the current backend platform without changing muxer-owned code.

This project is intended to produce:

- a reusable CGNAT framework that can be deployed in different AWS
  environments
- an operations model that defines where and how that framework is actually
  deployed
- a SoT interaction model that defines how customer intent, inventory,
  identity, addressing, and deployment inputs are exchanged with the source of
  truth
- a backend contract model that defines how the CGNAT HEAD END hands traffic to
  the current NAT-T and non-NAT backend head ends

This project remains isolated inside `CGNAT/` until:

- a first working version exists
- the infrastructure test deployment Go / No-Go gate passes
- and explicit approval is given for any work outside `CGNAT/`

## 2. Correct Nomenclature

### CGNAT HEAD END

Our platform-side component and the primary subject of this project.

Responsibilities:

- accepts the outer tunnel from the ISP side
- authenticates that outer tunnel with certificates
- establishes the trusted access path into the platform
- steers inner customer S2S VPN traffic across GRE to backend VPN head ends

### CGNAT ISP HEAD END

The customer/carrier-side component.

Responsibilities:

- establishes the outer certificate-authenticated tunnel to the CGNAT HEAD END
- sits between customer devices and the CGNAT HEAD END
- carries customer inner S2S VPN traffic through the outer tunnel

### Customer Devices

Devices behind the CGNAT ISP HEAD END.

Responsibilities:

- initiate the inner S2S VPN
- do not use certificates for the inner VPN
- use keys and known inside identity

### Backend VPN Head Ends

The existing RPDB NAT-T and non-NAT backend VPN head ends, treated as external
contract targets.

Responsibilities:

- receive inner VPN traffic from the CGNAT HEAD END across GRE
- present the public loopback identity
- terminate the inner VPN
- optionally NAT traffic from customer-original inside space to
  platform-assigned inside space
- provide correct return-path behavior

## 3. Required End-to-End Flow

```text
Customer Device
  ->
CGNAT ISP HEAD END
  ->
Outer certificate-authenticated tunnel
  ->
CGNAT HEAD END
  ->
GRE steering
  ->
selected backend NAT-T or non-NAT VPN head end
  ->
public loopback identity
  ->
inner S2S VPN termination
  ->
optional NAT from customer-original inside space
     to platform-assigned inside space
  ->
routing / services / return path
```

## 4. Core Technical Requirements

### Outer Tunnel

- initiated by the CGNAT ISP HEAD END
- authenticated by certificates
- must support unknown, changing, or CGNATed public source IP
- must not depend on fixed peer public IPs

### Inner VPN

- initiated by customer devices behind the CGNAT ISP HEAD END
- carried inside the outer tunnel
- does not use certificates
- uses normal customer VPN identity material:
  - keys
  - known inside customer source IP
- must be steerable to backend VPN head ends through an existing backend-facing
  contract

### Address Translation

- must support NAT from customer-original inside space to platform-assigned
  inside space
- reverse NAT must work correctly on return traffic

### Variable-Driven Infrastructure

- EC2 IP assignments must be modeled through variables/config
- subnet placement must be modeled through variables/config
- no important placement or addressing assumptions should be hardcoded in
  prototype code

### Framework Portability

- the CGNAT design must be usable as a framework deployable into different AWS
  environments
- environment-specific values must be supplied by variables, configuration, or
  SoT-driven inputs rather than embedded into the framework design

### Operations Model

- the design must separate reusable framework behavior from environment-specific
  deployment and operational choices
- it must be clear which values belong to the framework and which belong to the
  actual operational deployment context

### SoT Interaction

- the design must define how the framework consumes or exchanges data with the
  source of truth
- SoT interaction must cover customer identity, address assignment intent,
  backend inventory, and environment/deployment inputs
- the first implementation should assume CGNAT-owned record shapes even if the
  same database platform is reused

## 5. Fixed Placement Requirements

### CGNAT HEAD END

Must exist only in:

- `subnet-04a6b7f3a3855d438`

### CGNAT ISP HEAD END

Must span:

- `subnet-04a6b7f3a3855d438`
- `subnet-0e6ae1d598e08d002`

### Customer Devices

Must exist only in:

- `subnet-0e6ae1d598e08d002`

### Placement Modeling Rule

These subnet rules must be represented in variables/config and validated by the
CGNAT design.

## 6. Guardrails

### Guardrail 1: Workspace Boundary

All active CGNAT work must stay under `CGNAT/`.

That includes:

- docs
- configs
- scripts
- code
- tests
- build outputs

### Guardrail 2: Explicit Cross-Workspace Approval

If any work appears to require touching files outside `CGNAT/`:

1. stop
2. identify the exact file(s)
3. explain why the change is needed
4. wait for explicit approval

### Guardrail 3: Net-New Ingress Rule

CGNAT is a net-new ingress framework.

- no MUXER3 code import as implementation base
- no nested legacy repo clone
- no muxer code or schema changes as part of the current plan
- old ideas may inform requirements, but implementation stays in `CGNAT/`

### Guardrail 4: Backend Contract Target Rule

The current backend is treated as an external contract target.

- CGNAT may depend on documented backend behavior
- CGNAT does not assume the right to change muxer-owned internals
- any future proposal to change muxer or backend runtime behavior is a new stop
  point

### Guardrail 5: Publication Freeze

All CGNAT work remains local-only until first working version exists and is
reviewed.

- no GitHub push
- no CodeCommit push
- no CGNAT publication to remotes

## 7. Working Folder Structure

```text
CGNAT/
  README.md
  framework/
    docs/
      PROJECT_PLAN.md
      NOMENCLATURE.md
      ARCHITECTURE.md
      CONTROL_PLANE.md
      IDENTITY_MODEL.md
      VALIDATION_PLAN.md
      SECURITY_MODEL.md
      RISKS_AND_ASSUMPTIONS.md
      INTEGRATION_GATE.md
      SHARED_INTEGRATION_MAP.md
    config/
      cgnat-framework.example.yaml
      framework.example.json
      deployment-bundle.example.json
    scripts/
      build_bundle.py
      validate_bundle.py
      render_bundle.py
    src/
  aws/
    docs/
      INFRA_DEPLOYABLES.md
      OPERATIONS_MODEL.md
      PLACEMENT_AND_VARIABLES.md
      LAB_TOPOLOGY.md
    config/
      operations.example.json
    scripts/
  server/
    docs/
      OUTER_ACCESS_TUNNEL.md
      INNER_VPN_MODEL.md
      DATAPLANE.md
      ADDRESS_TRANSLATION.md
      SERVER_SIDE_SHAPES.md
    config/
    scripts/
  sot/
    docs/
      SOT_INTERACTION.md
    config/
      sot.example.json
  tests/
  build/
```

## 8. Phases and Gates

### Phase 1: Workspace Setup

Create the isolated `CGNAT/` workspace and record the rules.

Deliverables:

- `CGNAT/README.md`
- `CGNAT/framework/docs/PROJECT_PLAN.md`
- `CGNAT/framework/docs/NOMENCLATURE.md`

Gate:

- no further work until the workspace and rules are documented

### Phase 2: Architecture Definition

Define the complete CGNAT architecture using the corrected nomenclature.

Must define:

- CGNAT HEAD END role
- CGNAT ISP HEAD END role
- customer device role
- backend VPN head end role
- public loopback usage
- GRE steering model

Deliverables:

- `ARCHITECTURE.md`
- `OUTER_ACCESS_TUNNEL.md`
- `INNER_VPN_MODEL.md`

Gate:

- no implementation until outer vs inner responsibilities are explicit

### Phase 3: Placement and Variable Model

Define subnet placement and variable-driven infrastructure rules.

Must define:

- subnet role constraints
- EC2 IP/subnet assignment variables
- placement validation rules
- interface/address assumptions

Deliverables:

- `PLACEMENT_AND_VARIABLES.md`
- initial config examples under `CGNAT/aws/config/`, `CGNAT/sot/config/`, and
  `CGNAT/framework/config/`

Gate:

- no prototype code until placement and variable model are documented

### Phase 4: Control-Plane Design

Define how the system identifies and selects customer traffic.

Must define:

- outer cert-auth identity model
- unknown/changing public IP handling
- inner VPN identity model
- backend head-end selection
- mapping ownership between customer-original and assigned space
- framework-owned versus operations-owned values
- SoT-owned values and how they are consumed by the framework
- CGNAT-owned SoT record shape

Deliverables:

- `CONTROL_PLANE.md`
- `IDENTITY_MODEL.md`

Gate:

- no steering implementation until control-plane rules are clear

### Phase 5: Dataplane and NAT Design

Define how packets move and where NAT occurs.

Must define:

- nftables approach
- marking / RPDB policy routing
- GRE transport behavior
- steering to backend head ends
- inner VPN termination point
- NAT and reverse NAT location
- return-path symmetry
- MTU/MSS considerations
- backend-facing contract assumptions

Deliverables:

- `DATAPLANE.md`
- `ADDRESS_TRANSLATION.md`

Gate:

- no prototype code until packet flow and NAT flow are explicit

### Phase 6: Backend Contract and Lab / Demo Topology

Define the exact topology needed to prove the design.

Required components:

- one CGNAT HEAD END in `subnet-04a6b7f3a3855d438`
- one CGNAT ISP HEAD END spanning both subnets
- customer devices only in `subnet-0e6ae1d598e08d002`
- backend NAT-T and non-NAT VPN head ends
- test/core service nodes

Deliverable:

- `LAB_TOPOLOGY.md`
- `SHARED_INTEGRATION_MAP.md`

Gate:

- no infrastructure deployment discussion until topology is explicit
- no implementation assumes muxer changes

## 9. Infrastructure Test Deployment Go / No-Go Gate

This is the formal decision point before deploying any CGNAT infrastructure for
testing.

No infrastructure is deployed until this gate is explicitly passed.

### Preconditions for Go

All of these must be true:

- architecture docs are coherent
- nomenclature is fixed
- placement and variable model is documented
- control plane is defined
- dataplane/NAT model is defined
- lab topology is defined
- security and operational assumptions are written down
- framework versus operations boundaries are documented
- SoT interaction is documented well enough to support testing
- any expected impact outside `CGNAT/` is known

### Go / No-Go Questions

1. Do we understand the exact outer-tunnel cert-auth model?
2. Do we understand the exact inner-VPN model?
3. Do we know where NAT from customer-original to assigned space occurs?
4. Are subnet placement rules fully documented?
5. Are deployment variables defined?
6. Do we know exactly which AWS resources must be created?
7. Do we have a rollback approach for the test deployment?
8. Do we understand which values come from the framework, which come from
   operations, and which come from SoT?
9. Does deployment require touching files outside `CGNAT/`?
10. Is the current design mature enough to justify test infrastructure?
11. Have you explicitly approved moving from repo-only work to infrastructure
    deployment?

If any critical answer is "no," the result is No-Go.

### Go Outcome

If Go:

- we may prepare and deploy the minimum infrastructure needed for testing
- if that requires touching anything outside `CGNAT/`, we stop and ask first

### No-Go Outcome

If No-Go:

- no infrastructure is deployed
- work continues inside `CGNAT/` only

### Phase 7: Controlled Test Infrastructure Deployment

Only happens after a Go decision.

Scope:

- one CGNAT HEAD END in `subnet-04a6b7f3a3855d438`
- one CGNAT ISP HEAD END spanning both subnets
- customer devices only in `subnet-0e6ae1d598e08d002`
- connectivity to backend VPN head ends
- public loopback reachability model

Gate:

- if deployment work requires touching shared repo paths outside `CGNAT/`,
  stop and request approval

### Phase 8: Validation

Validate the real design behavior.

Validation targets:

- outer cert-auth tunnel establishment
- tolerance for unknown/changing public IP
- inner VPN carried through outer tunnel
- backend head-end selection
- public loopback termination model
- NAT from customer-original to assigned space
- return-path correctness
- placement-rule enforcement

Deliverables:

- `VALIDATION_PLAN.md`
- tests under `tests/`
- outputs under `build/`

Gate:

- no publication or integration discussion until validation shows a real
  working model

### Phase 9: First Working Version Gate

A first working version means:

- architecture docs are complete enough
- prototype code exists under `CGNAT/`
- outer tunnel model works
- inner VPN model works
- NAT-to-assigned-space model works
- placement and variable model is implemented
- validation demonstrates the design is real
- we both agree it is the first legitimate baseline

Only after this point can we discuss:

- publication to GitHub/CodeCommit
- touching files outside `CGNAT/`

### Phase 10: Integration Stop Point

This is the explicit stop point before anything outside the current folder
structure is touched.

If, after the first working version, we believe work outside `CGNAT/` is
needed:

1. stop
2. list the exact files outside `CGNAT/`
3. explain why each one must change
4. define the minimum required integration surface
5. wait for explicit approval

No exceptions.

## 10. Hard Blockers

The project is blocked until these are solved or clearly designed:

- outer tunnel cannot depend on fixed public peer IP
- outer tunnel must use cert auth
- inner VPN must work without certs
- backend VPN head-end steering must work
- backend public loopback termination model must be preserved
- NAT from customer-original to platform-assigned space must work
- subnet placement constraints must be enforced
- variable-driven EC2 IP/subnet assignment must be in place
- the framework must be defined as reusable across AWS environments
- the operations model must be explicit
- the SoT interaction model must be explicit
- the backend contract must be explicit without requiring muxer edits
- no work outside `CGNAT/` without approval
- no infrastructure deployment before the Go / No-Go gate passes
- no publication before the first working version review

## 11. Definition of Done for This Project Block

This initial CGNAT block is complete when:

- `CGNAT/` exists and is structured
- nomenclature is fixed and documented
- architecture is documented
- placement and variable model is documented
- prototype code exists entirely under `CGNAT/`
- validation demonstrates a first working version
- nothing outside `CGNAT/` was changed without approval
- no CGNAT work was pushed to GitHub or CodeCommit before review

## 12. Short Summary

This plan gives us:

- corrected role names
- exact subnet placement rules
- outer cert-auth tunnel
- inner non-cert customer VPN
- NAT to platform-assigned space
- backend VPN termination on public loopback
- variable-driven EC2 IP/subnet assignment
- a reusable AWS-deployable framework target
- a separate operations model for where and how the framework is deployed
- a first-class SoT interaction requirement
- strict workspace isolation
- a formal Go / No-Go gate before infrastructure deployment
- a hard stop before touching anything outside `CGNAT/`
