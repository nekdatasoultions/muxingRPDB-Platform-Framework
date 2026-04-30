# Backend Integration Plan

## Purpose

This document defines how the CGNAT Scenario 1 flow integrates with the
already-deployed RPDB customer provisioning and deployment path.

The goal is to reuse the existing backend customer lifecycle where it helps,
while keeping CGNAT ingress and transport logic owned inside `CGNAT/`.

## Integration Principle

CGNAT is a new ingress and transport layer.

The existing RPDB backend remains the current customer-service termination
layer.

So the integration model is:

- CGNAT owns:
  - outer cert-auth access tunnel
  - CGNAT HEAD END
  - GRE handoff
  - ISP/customer-side demo packaging
- existing RPDB deploy flow owns:
  - backend customer request validation
  - backend allocation planning
  - backend dry-run/live deploy orchestration

## Reuse Seams

The primary reuse points are:

- `muxer/scripts/provision_customer_request.py`
- `muxer/scripts/provision_customer_end_to_end.py`
- `scripts/customers/deploy_customer.py`

The CGNAT integration wrapper should call these as black-box entry points,
not reimplement them.

## Backend Request Mapping

The CGNAT wrapper generates a backend-native customer request from the CGNAT
bundle and a small integration config.

### Important Mapping Rule

For the CGNAT-carried inner tunnel:

- `peer.public_ip` is mapped to the customer loopback identity
- `peer.remote_id` is also mapped to the customer loopback identity

This is intentional.

The outer tunnel public source IP is unstable and belongs to the ISP access
context.

The stable backend-facing identity for the inner tunnel is the customer
loopback.

## Required Integration Inputs

The wrapper needs a small integration config in addition to the CGNAT bundle:

- target deployment environment
- backend customer request name
- backend PSK secret reference
- service-side local/core subnet derivation mode
- IPsec policy defaults
- initiation policy

Current live config:

- [scenario1-backend-integration.rpdb-empty-live.json](</E:/Code1/muxingRPDB Platform Framework-main/CGNAT/framework/config/scenario1-backend-integration.rpdb-empty-live.json>)

For Scenario 1, the backend request now derives `selectors.local_subnets` from
the selected customer-facing public loopback by default. In the current live
bundle, that means the backend request uses:

- `23.20.31.151/32`

If a future scenario needs a wider service-side selector set, that can be
overridden explicitly in the integration config.

## Dry-Run Plan

The safe path to deployment stage is:

1. generate the backend-native customer request from the CGNAT bundle
2. validate that request with existing RPDB request validation
3. run `deploy_customer.py --dry-run` against `rpdb-empty-live`
4. review the generated backend deployment plan alongside the CGNAT predeploy
   review package

## Why This Is Safe

- no muxer/backend code changes are required
- the existing deploy path remains the authority for backend planning
- CGNAT only adapts its own inputs into the current backend contract

## Current Limitation

This integration reuses the deployed path at the dry-run/deployment-stage level
first.

Live backend apply remains a later reviewed step after:

- CGNAT infrastructure create is approved
- backend dry-run is approved
- host-side CGNAT apply package is approved
