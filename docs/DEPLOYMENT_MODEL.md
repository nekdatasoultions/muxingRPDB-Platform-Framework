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
- Deployment should consume a framework-side handoff directory instead of
  rebuilding merged customer artifacts on its own.

## Planned Flow

1. validate one customer source
2. build one merged customer module and DynamoDB item
3. export one framework-side handoff directory
4. render one customer's muxer and head-end artifacts
5. package those artifacts into a reviewable bundle
6. verify backups and deployment preflight checks
7. apply muxer changes
8. apply head-end changes
9. validate customer dataplane/control-plane
10. rollback using documented steps if validation fails

## First Deployment Helpers

The first deployment branch helpers are intentionally preflight-oriented:

- [verify_backup_baseline.py](/E:/Code1/muxingRPDB%20Platform%20Framework/scripts/backup/verify_backup_baseline.py)
- [create_prechange_backup_note.py](/E:/Code1/muxingRPDB%20Platform%20Framework/scripts/backup/create_prechange_backup_note.py)
- [assemble_customer_bundle.py](/E:/Code1/muxingRPDB%20Platform%20Framework/scripts/packaging/assemble_customer_bundle.py)
- [build_customer_bundle_manifest.py](/E:/Code1/muxingRPDB%20Platform%20Framework/scripts/packaging/build_customer_bundle_manifest.py)
- [validate_customer_bundle.py](/E:/Code1/muxingRPDB%20Platform%20Framework/scripts/packaging/validate_customer_bundle.py)
- [deployment_readiness_check.py](/E:/Code1/muxingRPDB%20Platform%20Framework/scripts/deployment/deployment_readiness_check.py)
- [create_rollout_notes.py](/E:/Code1/muxingRPDB%20Platform%20Framework/scripts/deployment/create_rollout_notes.py)
- [run_double_verification.py](/E:/Code1/muxingRPDB%20Platform%20Framework/scripts/deployment/run_double_verification.py)

## Double Verification Gate

Before any live-node apply rehearsal, run the full cross-branch proof path in:

- [PRE_DEPLOY_DOUBLE_VERIFICATION.md](/E:/Code1/muxingRPDB%20Platform%20Framework/docs/PRE_DEPLOY_DOUBLE_VERIFICATION.md)

## Handoff Boundary

The framework branch is responsible for exporting a stable customer-scoped
handoff directory containing:

- `customer-module.json`
- `customer-ddb-item.json`
- `customer-source.yaml`
- `muxer/`
- `headend/`

The deployment branch is responsible for packaging, validating, and preflighting
that handoff output before any live-node apply logic is added.

## Current Platform Baseline

The repo now also carries imported current-state platform deploy assets for the
base empty environment:

- [CURRENT_PLATFORM_IMPORT.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/CURRENT_PLATFORM_IMPORT.md)
- [infra/cfn](/E:/Code1/muxingRPDB%20Platform%20Framework-main/infra/cfn)
- [scripts/platform](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts/platform)

That lets the repo hold both:

- current-state base platform deploy references
- RPDB-native customer lifecycle and verification flow
