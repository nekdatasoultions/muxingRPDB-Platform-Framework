# Infra Deployables

## Purpose

This document breaks the CGNAT design into the pieces that are actually
infrastructure deployables.

For this project, "infra deployables" means AWS-side resources and placement
choices that must exist before the server-side CGNAT behavior can be configured.

## What Counts as Infra Deployables

### CGNAT HEAD END Infrastructure

Deployable infrastructure for the CGNAT HEAD END includes:

- EC2 instance definition
- subnet placement in `subnet-04a6b7f3a3855d438`
- instance type
- public EIP allocation or association
- interface placement used by the server-side tunnel and GRE logic

### CGNAT ISP HEAD END Infrastructure

Deployable infrastructure for the CGNAT ISP HEAD END includes:

- EC2 instance definition
- transit-side subnet placement in `subnet-04a6b7f3a3855d438`
- customer-side subnet placement in `subnet-0e6ae1d598e08d002`
- interface layout across those subnets
- any public-side attachment needed for the outer tunnel source path

### Shared Environment Infrastructure

Environment-level infrastructure deployables include:

- AWS region selection
- VPC selection
- subnet IDs
- any environment-specific network attachments required to host the roles

## What Is Not an Infra Deployable

These are not treated as infra deployables in the current CGNAT framework
shape:

- backend VPN head ends themselves, if they already exist as shared RPDB
  infrastructure
- customer service intent from SoT
- server-side tunnel, GRE, steering, and translation configuration

Those belong to external dependency or server-side categories.

## External Dependencies

Some values are required by the infra deployment shape but are better modeled as
dependencies rather than deployables:

- certificate references
- backend VPN head-end inventory
- existing shared GRE inventory reference
- public loopback values on existing backend nodes

These may exist before the CGNAT deployment is applied.

## Current Infra Shape

In the current config model, the main infra deployable inputs come from the
`operations` section:

- `aws`
- `cgnat_head_end`
- `cgnat_isp_head_end`

## Acceptance Criteria

This document is complete enough for the current phase when:

- the AWS-deployable resource layer is separated from server-side config
- the role placement rules are explicit
- dependencies are not mislabeled as infra deployables
