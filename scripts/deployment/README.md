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

Example:

```powershell
python scripts\deployment\deployment_readiness_check.py `
  --customer-name example-nat-0001 `
  --bundle-dir build\customer-bundle
python scripts\deployment\create_rollout_notes.py `
  --customer-name example-nat-0001 `
  --out-dir notes\example-nat-0001
```

Planned next helpers:

- customer-scoped apply orchestration
- customer-scoped validation wrappers
- rollback helper entrypoints
