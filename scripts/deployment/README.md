# Deployment Scripts

This directory holds customer-scoped deployment helpers.

Current helper:

- `deployment_readiness_check.py`
  - verifies the customer bundle has manifest/checksum files
  - verifies the required baseline snapshots exist
  - verifies optional rollout-specific pre-change and rollback notes
- `create_rollout_notes.py`
  - creates `rollout.md` and `rollback.md` templates for one customer-scoped
    change
- `run_double_verification.py`
  - runs the full repo-only verification path across the framework and
    deployment branches for one customer
  - stops on the first failure and writes a JSON summary for review

Example:

```powershell
python scripts\deployment\deployment_readiness_check.py `
  --customer-name example-nat-0001 `
  --bundle-dir build\customer-bundle
python scripts\deployment\create_rollout_notes.py `
  --customer-name example-nat-0001 `
  --out-dir notes\example-nat-0001
python scripts\deployment\run_double_verification.py `
  --framework-repo "E:\Code1\muxingRPDB Platform Framework-fw" `
  --deployment-repo "E:\Code1\muxingRPDB Platform Framework-deploy" `
  --customer-source "muxer\config\customer-sources\examples\example-nat-0001\customer.yaml" `
  --environment-file "muxer\config\environment-defaults\example-environment.yaml" `
  --baseline-dir "E:\Code1\muxingRPDB Platform Framework\build\verification-fixtures\pre-rpdb-baseline"
```

Planned next helpers:

- customer-scoped apply orchestration
- customer-scoped validation wrappers
- rollback helper entrypoints
