# RPDB Documentation Index

## Start Here

Use this file as the entry point for the RPDB platform documentation.

The docs folder is intentionally kept focused on documents that are useful for
operators, engineers, and reviewers. Historical project plans, dated status
reports, and superseded notes are kept in Git history instead of the active docs
tree.

## Current Supported Path

These documents describe the current validated RPDB-empty platform and customer
workflow.

- [Muxer and head-end platform deploy checklist](MUXER_AND_HEADEND_PLATFORM_DEPLOY_CHECKLIST.md)
- [Fresh empty platform runbook](FRESH_EMPTY_PLATFORM_RUNBOOK.md)
- [Customer onboarding user guide](CUSTOMER_ONBOARDING_USER_GUIDE.md)
- [Pre-deploy double verification](PRE_DEPLOY_DOUBLE_VERIFICATION.md)
- [Backup and rollback baseline](BACKUP_AND_ROLLBACK_BASELINE.md)

## Technical Demo And Training

- [RPDB technical demo walkthrough](RPDB_TECHNICAL_DEMO_WALKTHROUGH.md)
- [How the muxer works](MUXER_GUIDE.md)
- [MUXER3 to RPDB major differences](MUXER3_TO_RPDB_MAJOR_DIFFERENCES.md)

## Architecture And Guardrails

- [RPDB target architecture](RPDB_TARGET_ARCHITECTURE.md)
- [RPDB MOM control-plane architecture](RPDB_MOM_CONTROL_PLANE_ARCHITECTURE.md)
- [RPDB core engineering guardrails](RPDB_CORE_ENGINEERING_GUARDRAILS.md)
- [Automatic NAT-T promotion project plan](RPDB_AUTOMATIC_NAT_T_PROMOTION_PROJECT_PLAN.md)
- [Dynamic-routing project plan](DYNAMIC_ROUTING_PROJECT_PLAN.md)
- [Database bootstrap](DATABASE_BOOTSTRAP.md)
- [Head-end customer orchestration](HEADEND_CUSTOMER_ORCHESTRATION.md)

The current supported platform path uses:

- the single-muxer CloudFormation surface under `infra/cfn`
- the VPN head-end unit CloudFormation surface under `infra/cfn`
- the RPDB customer provisioning and deployment scripts under `muxer/scripts`
  and `scripts/customers`
- the CGNAT framework under `CGNAT/`

## Migration And Reference Path

These documents are intentionally kept for migration, lab, or operator
reference work. They are not the primary validated onboarding path for new
RPDB-empty or CGNAT canary work.

- [Manual Linux customer provisioning](MANUAL_LINUX_CUSTOMER_PROVISIONING.md)
- [Live customer migration example](../muxer/docs/LIVE_CUSTOMER_MIGRATION_EXAMPLE.md)
- [Live NAT customer migration example](../muxer/docs/LIVE_NAT_CUSTOMER_MIGRATION_EXAMPLE.md)
- migrated customer requests under `muxer/config/customer-requests/migrated`
- migrated customer sources under `muxer/config/customer-sources/migrated`

## Current-State Reference

The `current-state` folder now keeps only a small amount of retained reference
material. Older node-specific deployment snapshots and runtime status files
were retired once the legacy muxer and legacy head-end tiers were removed.

- [Head-end active/standby model](current-state/HEADEND_HA_ACTIVE_STANDBY.md)

Removed current-state snapshots remain recoverable from Git history if we need
to audit the older environment.

## Muxer Internals

The detailed muxer model docs live under [muxer/docs](../muxer/docs). Start
with:

- [Provisioning input model](../muxer/docs/PROVISIONING_INPUT_MODEL.md)
- [Dynamic NAT-T provisioning](../muxer/docs/DYNAMIC_NAT_T_PROVISIONING.md)
- [Resource allocation model](../muxer/docs/RESOURCE_ALLOCATION_MODEL.md)
- [Translation and bridge scale decisions](../muxer/docs/TRANSLATION_AND_BRIDGE_SCALE_DECISIONS.md)
- [nftables batch render model](../muxer/docs/NFTABLES_BATCH_RENDER_MODEL.md)
- [Head-end outside NAT and overlap model](../muxer/docs/HEADEND_OUTSIDE_NAT_AND_OVERLAP_MODEL.md)
- [Bidirectional IPsec initiation](../muxer/docs/BIDIRECTIONAL_IPSEC_INITIATION.md)

## What Was Removed From Active Docs

The active docs tree no longer carries dated project plans, old readiness
reports, superseded scale notes, or CodeCommit import notes. They were useful
while building the repo, but they are not operator-facing source material.

Those files remain recoverable from Git history if we need to audit how a
decision was reached.
