# CGNAT Customer Provisioning Integration Design

## Purpose

This document defines how CGNAT customer provisioning should integrate with the
existing RPDB customer provisioning and deployment flow.

The goal is to keep the current RPDB deployment shape intact while adding
CGNAT as another supported transport family with its own configuration,
package-generation, target-selection, and apply behavior.

## Core Decision

CGNAT integration should follow the same operational shape as the existing
deploy flow:

- request validation
- repo-only package generation
- readiness review
- environment-driven target selection
- approved live apply
- validation
- rollback

The design should not introduce a second, unrelated deployment philosophy.

## Existing Deploy Shape

Today the shared RPDB customer flow is organized around these layers:

1. `muxer/scripts/provision_customer_request.py`
   - validates and allocates a customer request
   - generates the customer source, customer module, DDB item, and allocation
     items

2. `muxer/scripts/prepare_customer_pilot.py`
   - generates the repo-only review package
   - builds rendered, handoff, bound, and bundle artifacts

3. `muxer/scripts/provision_customer_end_to_end.py`
   - wraps the repo-only package flow into one entry point

4. `scripts/customers/deploy_customer.py`
   - validates the deployment environment
   - selects targets
   - runs dry-run gates
   - optionally runs approved live apply

5. `scripts/customers/live_apply_lib.py`
   - prepares muxer and head-end activation payloads
   - applies backend DDB payloads
   - applies muxer runtime and customer payloads
   - applies active and standby head-end payloads

The current model already has a clear lifecycle.

CGNAT should fit into that lifecycle, not replace it.

## Important Constraint

The existing deploy flow does not discover target hosts from DynamoDB.

Target hosts are selected from the deployment environment YAML, for example:

- `muxer/config/deployment-environments/rpdb-empty-live.yaml`

That means:

- DynamoDB remains the source of truth for customer and allocation state
- environment YAML remains the source of truth for which muxer and head-end
  instances are touched

CGNAT should follow this same rule.

## Integration Principles

### 1. Keep the Existing Spine

The following should remain true after CGNAT integration:

- existing non-NAT and NAT-T customers still use the current path
- existing environment YAML files still work
- existing dry-run and live-apply gates still exist
- existing rollback behavior still exists

### 2. Add a New Transport Family

CGNAT should be modeled as another transport family, not as a backend class.

The current backend family distinction remains:

- `non_nat`
- `nat`

CGNAT is an ingress/transport mode layered in front of that backend.

### 3. Reuse Existing Backend Provisioning

CGNAT should continue to reuse the existing backend customer packaging and
deployment logic wherever possible.

That means the backend non-NAT or NAT-T service still goes through the current
RPDB provisioning path.

### 4. Add CGNAT-Specific Surfaces Explicitly

The shared deploy path must gain explicit support for:

- CGNAT customer metadata
- CGNAT target selection
- CGNAT package generation
- CGNAT live apply
- CGNAT validation and rollback

## Target Integrated Shape

The target provisioning shape becomes:

```text
Customer Request
  ->
Provision customer source/module/allocation
  ->
Generate backend package
  ->
Generate muxer package additions
  ->
Generate CGNAT head-end package
  ->
Build one combined readiness/deploy review
  ->
Select targets from environment YAML
  ->
Apply backend
  ->
Apply muxer
  ->
Apply CGNAT head end
  ->
Validate
```

## Proposed Data Model Changes

### Customer Request / Source

The request and rendered source should gain an explicit transport selector.

Recommended shape:

```yaml
customer:
  name: example-customer
  customer_class: non-nat
  transport:
    mode: cgnat
    cgnat:
      service_profile: scenario1
      outer_identity_ref: customer-router-1/example-customer
      outer_auth_ref: pki/cgnat/customer-router-1
      customer_loopback_ip: 10.250.1.10
      known_inside_identity: 10.20.30.10/32
      service_reachable_subnets:
        - 23.20.31.151/32
        - 194.138.36.86/32
```

Recommended transport mode values:

- `direct_non_nat`
- `direct_nat_t`
- `cgnat`

The absence of a transport block should preserve the current legacy behavior.

### Customer Module

The customer module should preserve enough transport metadata for downstream
package and apply logic to branch correctly.

At minimum the module or its adjacent source should preserve:

- `transport.mode`
- backend family
- CGNAT outer identity/auth references
- customer loopback IP
- known inside identity
- service selectors

## Proposed Environment Target Changes

The current environment target selection shape should remain the model.

Today it looks roughly like:

- `targets.muxer`
- `targets.headends.nat.active`
- `targets.headends.nat.standby`
- `targets.headends.non_nat.active`
- `targets.headends.non_nat.standby`

CGNAT should be added in the same style.

Recommended shape:

```yaml
targets:
  muxer:
    ...
  headends:
    nat:
      active: ...
      standby: ...
    non_nat:
      active: ...
      standby: ...
  cgnat:
    headend:
      active:
        name: cgnat-headend-a
        role: cgnat-headend
        rpdb_managed: true
        selector:
          type: instance_id
          value: i-xxxxxxxxxxxxxxxxx
          private_ip: 172.31.x.x
        access:
          method: ssh
```

Future expansion can add:

- `cgnat.headend.standby`
- `cgnat.ingress`
- `cgnat.observability`

But the first implementation only needs one hosted CGNAT head-end target.

## Target Selection Behavior

`deploy_customer.py` should keep selecting targets from the environment YAML.

For CGNAT customers, target selection should return:

- `muxer`
- `headend_family`
- `headend_active`
- `headend_standby`
- `cgnat_headend_active`
- datastores / artifacts / backups

The backend family is still selected from the customer/package:

- `nat`
- `non_nat`

The new transport mode selects whether the CGNAT target must also be present.

## Repo-Only Package Design

For CGNAT customers, the repo-only package should contain three logical parts:

1. backend package
   - existing RPDB customer package

2. muxer package
   - current muxer activation/runtime bundle
   - any CGNAT-specific ingress additions if required

3. CGNAT package
   - outer peer/customer payload for the hosted CGNAT head end
   - any generated cert/identity references
   - any route or xfrm-specific customer artifacts

Recommended combined package layout:

```text
package/
  customer-source.yaml
  customer-module.json
  ...
  backend/
  muxer/
  cgnat/
  readiness.json
  validation.json
  rollback-plan.json
```

This can be implemented initially as an additive package rooted in `CGNAT/`
and later merged into the shared packaging path.

## Live Apply Design

The live apply adapter should follow the same general flow as the current one.

Recommended CGNAT apply order:

1. apply backend customer payloads
2. validate backend customer payloads
3. apply muxer payloads/runtime updates
4. validate muxer
5. apply CGNAT head-end customer payload
6. validate CGNAT head end
7. write combined apply journal and rollback plan

Rationale:

- backend responder should exist before CGNAT-side traffic arrives
- muxer/service ingress should exist before CGNAT customer traffic is used
- CGNAT customer activation should be last among the transport components

## Validation Design

The CGNAT-integrated deploy path should keep the current validation style:

- repo-only validation
- bound/bundle validation
- staged validation where applicable
- approved live validation

Additional CGNAT validation should include:

- outer customer tunnel validation on the hosted CGNAT head end
- inner selector and loopback identity validation
- muxer ingress/forwarding validation for CGNAT-carried traffic
- backend responder validation

## Rollback Design

CGNAT rollback should be additive to the current rollback model.

Recommended order:

1. remove CGNAT head-end customer payload
2. remove muxer CGNAT activation payload
3. remove backend customer payloads if the customer itself is being removed

If the backend customer already existed and only CGNAT enablement is being
reverted, backend rollback should be optional and controlled by the operation.

## Recommended First Implementation Boundary

The safest first implementation is:

- extend the shared model to recognize `transport.mode = cgnat`
- keep the existing backend provisioning flow
- add a new CGNAT-specific package/apply layer
- keep the first integration code in `CGNAT/` while reusing shared scripts as
  black-box steps

After the integrated flow is stable, the shared deploy path can absorb more of
the CGNAT logic.

## Non-Goals for the First Integration

The first integration should not try to solve:

- every future CGNAT topology
- multi-CGNAT-head-end HA
- automatic host discovery from DynamoDB
- full shared-schema refactoring across muxer-owned code
- every legacy migration path in one step

## Success Criteria

This design is successful when:

1. an RPDB customer request can explicitly declare `transport.mode = cgnat`
2. the deploy flow still selects muxer/backend hosts from environment YAML
3. backend provisioning is reused, not reimplemented
4. a CGNAT head-end package is generated alongside the backend package
5. approved live apply can touch backend, muxer, and CGNAT head-end in one
   controlled workflow
6. existing direct non-NAT and NAT-T customer flows still pass regression
