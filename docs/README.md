# RPDB Documentation Index

## Start Here

Use this file as the entry point for the RPDB platform documentation.

The docs folder is intentionally kept focused on documents that are useful for
operators, engineers, and reviewers. Historical project plans, dated status
reports, and superseded notes are kept in Git history instead of the active docs
tree.

## Operator Workflows

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
- [RPDB core engineering guardrails](RPDB_CORE_ENGINEERING_GUARDRAILS.md)
- [Automatic NAT-T promotion project plan](RPDB_AUTOMATIC_NAT_T_PROMOTION_PROJECT_PLAN.md)
- [Dynamic-routing project plan](DYNAMIC_ROUTING_PROJECT_PLAN.md)
- [Database bootstrap](DATABASE_BOOTSTRAP.md)
- [Head-end customer orchestration](HEADEND_CUSTOMER_ORCHESTRATION.md)

## Current-State Reference

The `current-state` folder contains imported baseline references for the
existing deploy shape. Treat these as reference material, not the final RPDB
architecture:

- [Deployment runbook](current-state/DEPLOYMENT_RUNBOOK.md)
- [Deploy muxer, VPN head ends, and customer runbook](current-state/DEPLOY_MUXER_HEADENDS_AND_CUSTOMER_RUNBOOK.md)
- [CloudFormation and NetBox SoT runbook](current-state/CLOUDFORMATION_NETBOX_RUNBOOK.md)
- [Head-end active/standby model](current-state/HEADEND_HA_ACTIVE_STANDBY.md)
- [Head-end runtime status](current-state/HEADEND_RUNTIME_STATUS.md)
- [Stack SoT for us-east-1](current-state/STACK_SOT_US_EAST_1.md)

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
