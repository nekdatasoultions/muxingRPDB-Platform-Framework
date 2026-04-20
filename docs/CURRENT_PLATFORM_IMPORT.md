# Current Platform Import

## Goal

Bring the current deployable platform references into the RPDB repo without
pretending the full platform story has already been redesigned.

This gives us one place to work from while we continue the RPDB migration.

## What Was Imported

### Current-State Runbooks

Imported under [current-state](/docs/current-state):

- [DEPLOYMENT_RUNBOOK.md](/docs/current-state/DEPLOYMENT_RUNBOOK.md)
- [DEPLOY_MUXER_HEADENDS_AND_CUSTOMER_RUNBOOK.md](/docs/current-state/DEPLOY_MUXER_HEADENDS_AND_CUSTOMER_RUNBOOK.md)
- [CLOUDFORMATION_NETBOX_RUNBOOK.md](/docs/current-state/CLOUDFORMATION_NETBOX_RUNBOOK.md)
- [HEADEND_HA_ACTIVE_STANDBY.md](/docs/current-state/HEADEND_HA_ACTIVE_STANDBY.md)
- [HEADEND_RUNTIME_STATUS.md](/docs/current-state/HEADEND_RUNTIME_STATUS.md)

### CloudFormation Assets

Imported under [infra/cfn](/infra/cfn):

- muxer templates and parameter files
- VPN head-end templates and parameter files
- current example and `us-east-1` parameter sets

### Base Platform Scripts

Imported under [scripts/platform](/scripts/platform):

- CloudFormation deploy helpers
- CloudFormation validation helpers
- project packaging helpers
- current bootstrap utilities like `resume_headend_bootstrap.sh`
- current template parameter generator `netbox_to_cfn_params.py`

## How To Use This Right Now

### Fresh Empty Platform

For a fresh environment with no customers yet:

1. start with the current-state platform docs in [docs/current-state](/docs/current-state)
2. use the imported CloudFormation assets in [infra/cfn](/infra/cfn)
3. use the imported base deploy scripts in [scripts/platform](/scripts/platform)
4. make the database layer explicit with [DATABASE_BOOTSTRAP.md](/docs/DATABASE_BOOTSTRAP.md) and [ensure_dynamodb_tables.py](/scripts/platform/ensure_dynamodb_tables.py)
5. use the RPDB-native front door in [FRESH_EMPTY_PLATFORM_RUNBOOK.md](/docs/FRESH_EMPTY_PLATFORM_RUNBOOK.md) and [deploy_empty_platform.py](/scripts/platform/deploy_empty_platform.py)
6. after the empty platform exists and the customer SoT table is ensured, move into the RPDB-native customer flow

### Customer Onboarding

For customer onboarding in the new model, use the RPDB-native pieces already in
this repo:

- per-customer source files under [muxer/config/customer-sources](/muxer/config/customer-sources)
- render/export/bind scripts under [muxer/scripts](/muxer/scripts)
- packaging and readiness scripts under [scripts](/scripts)

## Boundary

These imported assets are the **current-state baseline**, not the final RPDB
platform architecture.

That means:

- they are here so we can work from one repo
- they reflect the currently proven deploy model
- they will later be refined into a more cohesive RPDB-native platform story
