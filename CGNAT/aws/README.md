# AWS Lane

This lane holds AWS-side assets:

- infrastructure and placement documents
- operations/environment config
- AWS deployment scripts

Use this lane for things that describe or drive AWS resource deployment.

Current live-environment baseline files:

- `config/operations.rpdb-empty-live.json`
- `scripts/preflight_scenario1_aws.py`

The live preflight is the place where real AWS shape checks happen before any
apply step is allowed.
