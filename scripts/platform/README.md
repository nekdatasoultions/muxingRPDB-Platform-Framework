# Platform Scripts

This directory contains imported current-state platform scripts for:

- CloudFormation validation
- CloudFormation deploy
- S3 packaging
- bootstrap support utilities

## Current Supported Path

Use these when you need to stand up or validate the **base platform**:

- muxer
- NAT VPN head-end pair
- non-NAT VPN head-end pair
- supporting package artifacts
- the platform database baseline through [ensure_dynamodb_tables.py](ensure_dynamodb_tables.py)
  - customer SoT table
  - resource allocation table for smart provisioning
- the new empty-platform front door through [deploy_empty_platform.py](deploy_empty_platform.py)
- safe rehearsal parameter generation through [prepare_empty_platform_params.py](prepare_empty_platform_params.py)
- post-bootstrap head-end verification through [verify_headend_bootstrap.py](verify_headend_bootstrap.py)

The muxer runtime source for this repo now lives under:

- [muxer/runtime-package](../../muxer/runtime-package)

That means the empty-platform wrapper packages the RPDB runtime from this repo
rather than reaching back into any sibling legacy muxer repo.

Use the other script areas for RPDB-native customer lifecycle work:

- [backup](../backup)
- [deployment](../deployment)
- [packaging](../packaging)

For the database side of a fresh empty platform deploy, start with:

- [DATABASE_BOOTSTRAP.md](../../docs/DATABASE_BOOTSTRAP.md)

For the full current production-shaped empty platform flow, start with:

- [FRESH_EMPTY_PLATFORM_RUNBOOK.md](../../docs/FRESH_EMPTY_PLATFORM_RUNBOOK.md)

## Migration And Reference Boundary

These scripts are part of the active RPDB-empty base-platform path.

They are not the place to look for:

- legacy multi-muxer deployment
- legacy regional CloudFormation wrappers
- legacy NetBox-driven parameter generation
- manual customer migration exercises

Legacy regional/multi-muxer and NetBox-driven CloudFormation helpers were
retired during the RPDB-empty cleanup. The current active path is:

- single muxer via `cfn_deploy_single_muxer.sh`
- NAT head-end pair via `cfn_deploy_vpn_headend.sh`
- non-NAT head-end pair via `cfn_deploy_vpn_headend.sh`
