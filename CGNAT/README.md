# CGNAT Workspace

## Purpose

This directory is the working area for CGNAT architecture, planning,
implementation, scripts, tests, validation artifacts, and rollout guides.

CGNAT is treated as a transport and ingress layer in front of the existing
backend VPN platform. The goal is to let a single CGNAT head end feed the same
backend NAT-T and non-NAT service models that already exist in RPDB.

This work is intended to produce:

- a reusable CGNAT transport framework that can be deployed in different AWS
  environments
- a deployment model that integrates with the shared muxer and customer
  provisioning flow
- a topology model that supports multiple outer-tunnel ownership patterns
- a SoT interaction model that defines how intent, inventory, identity, and
  deployment inputs are exchanged with the source of truth

## Scope

The current target design supports one CGNAT transport family with two outer
topologies.

### Topology A: `per_customer_outer`

1. A customer device establishes an outer certificate-authenticated tunnel to
   the CGNAT head end.
2. That same customer device establishes an inner VPN tunnel through the outer
   path.
3. The CGNAT head end steers the inner traffic to the selected backend NAT-T
   or non-NAT VPN head ends.

### Topology B: `shared_isp_gateway`

1. An ISP CGNAT gateway establishes the outer certificate-authenticated tunnel
   to the CGNAT head end.
2. Customer devices behind that gateway establish only the inner VPN tunnel.
3. The CGNAT head end again steers the inner traffic to the selected backend
   NAT-T or non-NAT VPN head ends.

### Shared Principles

- One CGNAT head end must be able to support both topologies at the same time.
- The outer tunnel must not depend on a fixed public source IP.
- The inner tunnel terminates into the same backend service model as a regular
  VPN customer.
- Once the inner tunnel terminates, the customer should have the same feature
  envelope as a regular backend VPN service, including:
  - non-NAT behavior
  - NAT-T behavior
  - inside NAT
  - outside NAT
  - normal routing and policy behavior at the backend handoff

This means the project is not only about packet flow. It is also about:

- framework portability across AWS environments
- environment-specific operational deployment data
- shared provisioning and live apply integration
- first-class interaction with the SoT

## Guardrails

- CGNAT design, tests, artifacts, and rollout planning stay anchored under
  `CGNAT/`.
- Shared repo changes are allowed when they are part of the documented
  integration plan and protected by regression gates.
- No MUXER3 code is imported or reused as an implementation base.
- No live-node changes should be made until the relevant pre-live gates are
  green and a rollback path exists.
- Live remove/reapply work must be backup-first.
- Customer-device and ISP-gateway device cutover remain separate operator
  lanes, even when platform-side provisioning is automated.

## Workspace Lanes

- [Framework](./framework/README.md)
- [AWS](./aws/README.md)
- [Server](./server/README.md)
- [SoT](./sot/README.md)

Useful script entry points:

- [Scenario 1 local preparation orchestrator](./framework/scripts/prepare_scenario1.py)
- [Scenario 1 pre-deploy review packager](./framework/scripts/prepare_scenario1_predeploy_review.py)
- [AWS package builder](./aws/scripts/README.md)
- [Server package builder](./server/scripts/README.md)
- [Server host-apply packager](./server/scripts/prepare_scenario1_host_apply.py)

Useful live-environment baselines:

- `framework/config/deployment-bundle.rpdb-empty-live.json`
- `aws/config/operations.rpdb-empty-live.json`
- `sot/config/sot.rpdb-empty-live.json`

Useful cross-lane references:

- [Backend Contract Map](./framework/docs/SHARED_INTEGRATION_MAP.md)
- [Customer Provisioning Integration Design](./framework/docs/CUSTOMER_PROVISIONING_INTEGRATION_DESIGN.md)
- [Customer Provisioning Integration Plan](./framework/docs/CUSTOMER_PROVISIONING_INTEGRATION_PLAN.md)
- [Customer Provisioning Regression Gates](./framework/docs/CUSTOMER_PROVISIONING_REGRESSION_GATES.md)
- [CGNAT Topology Expansion Execution Plan](./framework/docs/CGNAT_TOPOLOGY_EXPANSION_EXECUTION_PLAN.md)

Rendered examples in `build/` now mirror the same split:

- `framework/`
- `aws/`
- `server/`
- `sot/`

## Working Layout

```text
CGNAT/
  README.md
  framework/
    docs/
    config/
    scripts/
    src/
  aws/
    docs/
    config/
    scripts/
  server/
    docs/
    config/
    scripts/
  sot/
    docs/
    config/
  tests/
  build/
```

## Current Shared Provisioning Boundary

The shared provisioning framework now covers:

- backend head-end customer state
- muxer customer state
- CGNAT head-end customer state
- PKI review and handoff material generation

The shared provisioning framework does not yet automatically perform:

- customer-device installation and cutover
- ISP gateway installation and cutover for `shared_isp_gateway`

Those remain operator-controlled steps after the platform-side review and apply
artifacts are generated.
