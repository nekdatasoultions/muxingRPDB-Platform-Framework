# Repository Scripts

This directory holds repository-level helpers for deployment workflow.

## Planned Layout

```text
scripts/
  backup/
  deployment/
  packaging/
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

The first step is still structure and workflow clarity, but this branch now
makes the deployment areas explicit so implementation can land into stable
paths later.
