# Repository Scripts

This directory holds repository-level helpers for deployment workflow.

## Planned Layout

```text
scripts/
  backup/
  deployment/
  packaging/
  platform/
```

## Intent

- `backup/`
  - backup verification helpers
  - restore helper scaffolds
- `deployment/`
  - customer-scoped apply orchestration
  - deployment preflight checks
- `packaging/`
  - bundle creation helpers
  - manifest and checksum helpers
- `platform/`
  - imported current-state base-platform deploy and packaging scripts

The first step is still structure and workflow clarity, but this branch now
makes the deployment areas explicit so implementation can land into stable
paths later.

Reference:

- [CURRENT_PLATFORM_IMPORT.md](../docs/CURRENT_PLATFORM_IMPORT.md)
