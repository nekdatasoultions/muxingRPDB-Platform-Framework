# CloudFormation Assets

This directory contains the current imported CloudFormation templates and
parameter files for the muxer and VPN head-end platform.

These are here so the RPDB repo can carry the same base-platform deployment
entrypoints while the customer lifecycle moves into the new model.

Current use:

- deploy a fresh empty platform
- validate current templates and parameter files
- compare future RPDB-native infra changes against the current baseline

Important boundary:

- these are imported current-state assets
- they are not yet reworked into a fully RPDB-native infrastructure model
