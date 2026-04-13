# Deployment Scripts

This directory holds customer-scoped deployment helpers.

Current helper:

- `deployment_readiness_check.py`
  - verifies the customer bundle has manifest/checksum files
  - verifies the required baseline snapshots exist
  - verifies optional rollout-specific pre-change and rollback notes

Example:

```powershell
python scripts\deployment\deployment_readiness_check.py `
  --customer-name example-nat-0001 `
  --bundle-dir build\customer-bundle
```

Planned next helpers:

- customer-scoped apply orchestration
- customer-scoped validation wrappers
- rollback helper entrypoints
