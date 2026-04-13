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
    customer/
      customer-summary.json
    routing/
      rpdb-routing.json
    tunnel/
      tunnel-intent.json
    firewall/
      firewall-intent.json
  headend/
    ipsec/
      ipsec-intent.json
    routing/
      routing-intent.json
    post-ipsec-nat/
      post-ipsec-nat-intent.json
```

## Required Files

- `customer-module.json`
- `customer-ddb-item.json`

## Recommended Files

- `customer-source.yaml`
- `export-metadata.json`

## Optional Directories

- `muxer/`
  - customer-scoped muxer artifacts
  - framework-generated intent files should be present even before final live
    apply artifacts exist
- `headend/`
  - customer-scoped head-end artifacts
  - framework-generated intent files should be present even before final live
    apply artifacts exist

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

If explicit artifact directories are not supplied, the export helper should
still generate reviewable intent files under `muxer/` and `headend/`.

## Render Helper

Use:

```powershell
python muxer\scripts\render_customer_artifacts.py `
  muxer\config\customer-sources\examples\example-nat-0001\customer.yaml `
  --out-dir build\render-example-nat-0001
```

This helper writes the same structured muxer/head-end artifact tree without the
top-level handoff files, which is useful for renderer-focused verification.
