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

## Required Head-End Files

To support customer-scoped head-end apply/remove orchestration, the bundle must
carry these files:

- `headend/ipsec/ipsec-intent.json`
- `headend/ipsec/swanctl-connection.conf`
- `headend/routing/routing-intent.json`
- `headend/routing/ip-route.commands.txt`
- `headend/post-ipsec-nat/post-ipsec-nat-intent.json`
- `headend/post-ipsec-nat/nftables.apply.nft`
- `headend/post-ipsec-nat/nftables.remove.nft`
- `headend/post-ipsec-nat/nftables-state.json`
- `headend/post-ipsec-nat/activation-manifest.json`

## Recommended Contents

- `customer/customer-source.yaml`

## Framework Handoff Inputs

The bundle assembler can consume a framework-side handoff export directory with
this shape:

```text
export/
  export-metadata.json
  customer-module.json
  customer-ddb-item.json
  customer-source.yaml
  muxer/
  headend/
```

## Assembly Helper

Use:

```powershell
# The handoff export is produced on rpdb-framework-scaffold.
# This branch consumes that exported directory.
python scripts\packaging\assemble_customer_bundle.py `
  --bundle-dir <bundle-dir> `
  --export-dir build\handoff\<customer-name>
```

Optional inputs:

- `--customer-name`
- `--customer-source`
- `--muxer-dir`
- `--headend-dir`
