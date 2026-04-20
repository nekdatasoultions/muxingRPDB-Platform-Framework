# Packaging

This directory defines how RPDB deployment artifacts should be packaged.

## Packaging Goals

- customer-scoped output bundles
- reviewable manifests
- checksum files
- deterministic artifact layout for muxer and head-end consumers

## Planned Bundle Shape

```text
bundle/
  manifest.txt
  sha256sums.txt
  customer/
    customer.yaml
    customer-ddb-item.json
  muxer/
    ...
  headend/
    ...
```

## Notes

- Packaging should consume generated artifacts, not raw source files alone.
- Bundles should be safe to review before apply.
- The same customer-scoped bundle should support apply and rollback context.
