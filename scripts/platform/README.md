# Platform Scripts

This directory contains imported current-state platform scripts for:

- CloudFormation validation
- CloudFormation deploy
- S3 packaging
- bootstrap support utilities

Use these when you need to stand up or validate the **base platform**:

- muxer
- NAT VPN head-end pair
- non-NAT VPN head-end pair
- supporting package artifacts
- the platform database baseline through [ensure_dynamodb_tables.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts/platform/ensure_dynamodb_tables.py)
- the new empty-platform front door through [deploy_empty_platform.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts/platform/deploy_empty_platform.py)

Use the other script areas for RPDB-native customer lifecycle work:

- [backup](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts/backup)
- [deployment](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts/deployment)
- [packaging](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts/packaging)

For the database side of a fresh empty platform deploy, start with:

- [DATABASE_BOOTSTRAP.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/DATABASE_BOOTSTRAP.md)

For the full current production-shaped empty platform flow, start with:

- [FRESH_EMPTY_PLATFORM_RUNBOOK.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/FRESH_EMPTY_PLATFORM_RUNBOOK.md)
