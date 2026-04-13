# Customer Bundle Layout

## Goal

A customer-scoped bundle should be reviewable before apply and reusable during
rollback analysis.

## Expected Layout

```text
bundle/
  bundle-metadata.json
  manifest.txt
  sha256sums.txt
  customer/
    customer-module.json
    customer-ddb-item.json
    customer-source.yaml        (recommended)
  muxer/
    ...
  headend/
    ...
```

## Required Contents

- `bundle-metadata.json`
- `manifest.txt`
- `sha256sums.txt`
- `customer/customer-module.json`
- `customer/customer-ddb-item.json`
- `customer/`
- `muxer/`
- `headend/`

## Recommended Contents

- `customer/customer-source.yaml`

## Assembly Helper

Use:

```powershell
python scripts\packaging\assemble_customer_bundle.py `
  --customer-name <customer-name> `
  --bundle-dir <bundle-dir> `
  --customer-module <customer-module-json> `
  --customer-ddb-item <customer-ddb-item-json>
```

Optional inputs:

- `--customer-source`
- `--muxer-dir`
- `--headend-dir`
