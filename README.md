# muxingRPDB-Platform-Framework

This repo is the new platform workspace for the RPDB-based muxing model.

The goal is to keep the next-generation control plane and dataplane design
separate from the currently deployed framework while we:

- move to one source file per customer
- keep DynamoDB as the canonical customer SoT
- make per-customer sync, render, and apply the default workflow
- keep fwmark-based steering, but make RPDB priorities explicit
- reduce full-fleet rebuild behavior before we touch production

This repo starts as scaffolding only. It is intentionally light so we can
design the model cleanly before migrating implementation code.

## Initial Layout

```text
docs/
infra/
muxer/
scripts/
```

## Current Intent

- `docs/`
  - architecture and migration notes for the RPDB model
- `infra/`
  - future infrastructure packaging and deployment assets
- `muxer/`
  - future customer source model, renderers, docs, and control-plane logic
- `scripts/`
  - shared operator and packaging helpers for this repo

## Guardrails

- Do not assume this repo is live-deployable yet.
- Do not point production nodes at this repo until the model is validated.
- Treat the current deployed framework as the stable reference until the RPDB
  path is complete.
