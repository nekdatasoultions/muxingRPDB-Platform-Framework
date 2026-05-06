# CloudFormation Assets

This directory contains the current imported CloudFormation templates and
parameter files for the RPDB-empty muxer and VPN head-end platform.

These are here so the RPDB repo can carry the same base-platform deployment
entrypoints while the customer lifecycle moves into the new model.

## Current Supported Path

Current use:

- deploy a fresh empty platform
- validate current templates and parameter files
- compare future RPDB-native infra changes against the current baseline

Current active surface:

- `muxer-single-asg.yaml`
- `vpn-headend-unit.yaml`
- `parameters.single-muxer.*`
- `parameters.vpn-headend.nat.graviton-efs.us-east-1.json`
- `parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json`
- `parameters.vpn-headend.nat.example.json`
- `parameters.vpn-headend.non-nat.example.json`

Important boundary:

- these are imported current-state assets
- they are not yet reworked into a fully RPDB-native infrastructure model
- the supported VPN head-end shape is now Graviton-only

## Migration And Reference Boundary

This folder now documents only the active RPDB-empty CloudFormation surface.

Legacy multi-muxer, regional, customer-vpn-ecs, and NetBox-oriented
CloudFormation artifacts were retired during the 2026-05-05 cleanup and should
be treated as historical material recoverable from Git history, not as current
deployment options.
