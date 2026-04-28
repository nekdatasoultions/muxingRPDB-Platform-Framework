# Operations Model

## Purpose

This document defines the operations layer for the CGNAT framework.

The operations layer is where the reusable framework becomes a concrete AWS
deployment shape. It owns deployment-time values, rollout choices, and
environment-specific inventory.

## Operations Role

The operations layer answers questions like:

- which AWS account and region is this deployed into
- which VPC and subnets are used
- which instances represent the CGNAT HEAD END and CGNAT ISP HEAD END
- which backend VPN head ends are reachable
- which certificate references are used
- how a test deployment is rolled forward or rolled back

## Required Operations Inputs

At minimum, operations inputs should provide:

- environment name
- AWS region
- VPC identifier
- CGNAT HEAD END placement
- CGNAT ISP HEAD END placement
- backend VPN head-end inventory
- GRE inventory reference and allocation policy
- outer-tunnel certificate references

## Placement Rules

Operations inputs must respect the approved placement constraints:

- CGNAT HEAD END only in `subnet-04a6b7f3a3855d438`
- CGNAT ISP HEAD END spanning:
  - `subnet-04a6b7f3a3855d438`
  - `subnet-0e6ae1d598e08d002`
- Customer Devices only in `subnet-0e6ae1d598e08d002`

The framework validator should reject operations input that violates these
constraints.

## Backend Inventory

Operations owns the concrete backend inventory visible in a given environment.

That includes:

- NAT-T backend entries
- non-NAT backend entries
- GRE remote targets
- public loopback values

The operations layer does not decide customer service intent on its own, but it
must provide the inventory that SoT and the framework can select from.

## GRE Inventory

Operations also owns the GRE inventory reference used by the CGNAT HEAD END.

For Scenario 1, the current rule is:

- use the existing shared GRE space already defined for the platform
- allocate the next available GRE endpoint assignment from that space

This keeps GRE allocation aligned with the current environment instead of
introducing a separate CGNAT-only GRE pool.

## Certificates and Secrets

Operations inputs should carry references to certificate material rather than
embedding private material directly in framework contracts.

This keeps the framework reusable and keeps operational secret handling in the
environment-owned layer.

## Rollout Expectations

Before test deployment, the operations layer should be able to answer:

- what resources will be created
- which resources are reused
- how the test can be rolled back
- what success signals indicate the environment is ready for traffic

## Go / No-Go Relevance

We are not ready for test deployment until operations data is concrete enough
to support:

- validated placement
- validated backend inventory
- validated GRE inventory reference and allocation rule
- validated certificate references
- clear rollback expectations

## Acceptance Criteria

This document is complete enough for the current phase when:

- operations-owned values are clearly separated from framework and SoT values
- placement and backend inventory responsibilities are explicit
- rollout expectations are explicit
