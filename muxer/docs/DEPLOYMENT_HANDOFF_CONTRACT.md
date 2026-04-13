# Deployment Handoff Contract

## Goal

The framework branch should export one stable customer handoff directory that
the deployment branch can consume without guessing filenames.

## Handoff Directory

The framework-side export should produce:

```text
export/
  export-metadata.json
  customer-module.json
  customer-ddb-item.json
  customer-source.yaml
  muxer/
    ...
  headend/
    ...
```

## Required Files

- `customer-module.json`
- `customer-ddb-item.json`

## Recommended Files

- `customer-source.yaml`
- `export-metadata.json`

## Optional Directories

- `muxer/`
  - customer-scoped muxer artifacts when available
- `headend/`
  - customer-scoped head-end artifacts when available

## Why This Matters

This keeps the branch boundary clean:

- the framework branch is responsible for generating customer-scoped artifacts
- the deployment branch is responsible for packaging and preflight workflow

The deployment branch should not need to know how to rebuild the merged module
or DynamoDB item from source files. It should receive them as handoff inputs.

## Export Helper

Use:

```powershell
python muxer\scripts\export_customer_handoff.py `
  muxer\config\customer-sources\examples\example-nat-0001\customer.yaml `
  --export-dir build\example-nat-0001
```

Optional inputs:

- `--muxer-dir`
- `--headend-dir`
