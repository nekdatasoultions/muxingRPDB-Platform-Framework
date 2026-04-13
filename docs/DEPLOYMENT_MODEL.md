# Deployment Model

## Goal

The RPDB deployment model should be backup-first and customer-scoped by
default.

That means:

1. verify backups before any live change
2. package artifacts intentionally
3. deploy one customer at a time unless a fleet action is explicitly intended
4. keep rollback documented and ready before apply logic is added

## Scope

The deployment model needs to cover:

- muxer packaging and apply
- VPN head-end packaging and apply
- customer-scoped deployment workflow
- rollback against the shared backup baseline

## Core Principles

- Backups are a hard gate, not a nice-to-have.
- Deployment should consume generated artifacts, not ad hoc node edits.
- One-customer apply should be the default operator flow.
- Fleet-wide actions should always be explicit.

## Planned Flow

1. validate one customer source
2. build one merged customer module and DynamoDB item
3. render one customer's muxer and head-end artifacts
4. package those artifacts into a reviewable bundle
5. verify backups and deployment preflight checks
6. apply muxer changes
7. apply head-end changes
8. validate customer dataplane/control-plane
9. rollback using documented steps if validation fails
