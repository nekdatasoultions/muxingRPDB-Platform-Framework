# muxingRPDB-Platform-Framework

This repo is the new platform workspace for the RPDB-based muxing model.

The goal is to keep the next-generation control plane and dataplane design
separate from the currently deployed framework while we:

- move to one source file per customer
- keep DynamoDB as the canonical customer SoT
- make per-customer sync, render, and apply the default workflow
- keep fwmark-based steering, but make RPDB priorities explicit
- reduce full-fleet rebuild behavior before we touch production

This repo now carries the RPDB platform framework, runtime package, customer
provisioning workflow, deployment helpers, and the current-state references we
need while moving away from the legacy muxer stack.

It holds:

- the current base-platform bootstrap references
- the new RPDB-native customer lifecycle model

## Layout

```text
docs/
infra/
muxer/
scripts/
```

## Current Intent

- `docs/`
  - the curated operator, architecture, and training docs
  - imported current-state platform references that still matter
- `infra/`
  - infrastructure packaging and deployment assets
  - imported current-state CloudFormation assets
- `muxer/`
  - customer source model, renderers, docs, runtime package, and control-plane logic
- `scripts/`
  - shared operator, deployment, verification, and packaging helpers
  - imported current-state base-platform deploy scripts

## Guardrails

- Do not modify MUXER3 from this repo.
- Do not touch AWS or live nodes without explicit approval.
- Do not apply a customer without an approved change window.
- Keep runtime and generated packet-handling artifacts on `nftables`, not
  `iptables` or `iptables-restore`.
- Treat customer onboarding as one customer file plus the RPDB deploy workflow,
  with platform values auto-assigned and tracked.

See:

- [RPDB documentation index](docs/README.md)
