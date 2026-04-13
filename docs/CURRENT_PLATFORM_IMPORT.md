# Current Platform Import

## Goal

Bring the current deployable platform references into the RPDB repo without
pretending the full platform story has already been redesigned.

This gives us one place to work from while we continue the RPDB migration.

## What Was Imported

### Current-State Runbooks

Imported under [current-state](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/current-state):

- [DEPLOYMENT_RUNBOOK.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/current-state/DEPLOYMENT_RUNBOOK.md)
- [DEPLOY_MUXER_HEADENDS_AND_CUSTOMER_RUNBOOK.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/current-state/DEPLOY_MUXER_HEADENDS_AND_CUSTOMER_RUNBOOK.md)
- [CLOUDFORMATION_NETBOX_RUNBOOK.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/current-state/CLOUDFORMATION_NETBOX_RUNBOOK.md)
- [HEADEND_HA_ACTIVE_STANDBY.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/current-state/HEADEND_HA_ACTIVE_STANDBY.md)
- [HEADEND_RUNTIME_STATUS.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/current-state/HEADEND_RUNTIME_STATUS.md)

### CloudFormation Assets

Imported under [infra/cfn](/E:/Code1/muxingRPDB%20Platform%20Framework-main/infra/cfn):

- muxer templates and parameter files
- VPN head-end templates and parameter files
- current example and `us-east-1` parameter sets

### Base Platform Scripts

Imported under [scripts/platform](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts/platform):

- CloudFormation deploy helpers
- CloudFormation validation helpers
- project packaging helpers
- current bootstrap utilities like `resume_headend_bootstrap.sh`
- current template parameter generator `netbox_to_cfn_params.py`

## How To Use This Right Now

### Fresh Empty Platform

For a fresh environment with no customers yet:

1. start with the current-state platform docs in [docs/current-state](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/current-state)
2. use the imported CloudFormation assets in [infra/cfn](/E:/Code1/muxingRPDB%20Platform%20Framework-main/infra/cfn)
3. use the imported base deploy scripts in [scripts/platform](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts/platform)
4. after the empty platform exists, move into the RPDB-native customer flow

### Customer Onboarding

For customer onboarding in the new model, use the RPDB-native pieces already in
this repo:

- per-customer source files under [muxer/config/customer-sources](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/config/customer-sources)
- render/export/bind scripts under [muxer/scripts](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/scripts)
- packaging and readiness scripts under [scripts](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts)

## Boundary

These imported assets are the **current-state baseline**, not the final RPDB
platform architecture.

That means:

- they are here so we can work from one repo
- they reflect the currently proven deploy model
- they will later be refined into a more cohesive RPDB-native platform story
