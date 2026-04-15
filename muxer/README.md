# Muxer

This directory holds the RPDB-based muxer work.

We are now treating it as two related but separate layers:

- `control plane`
  - the new RPDB customer model
  - per-customer source files
  - merge, validation, render, bind, and bundle logic
- `runtime package`
  - the deployable muxer runtime that will replace the current `MUXER3` bundle
  - copied forward selectively from `MUXER3`, then evolved here

The intent is to make the muxer workflow customer-scoped by default:

- validate one minimal request
- auto-allocate one customer namespace set
- source one customer
- sync one customer
- render one customer
- apply one customer

Current and planned subdirectories:

- `config/`
  - RPDB customer defaults and per-customer sources
  - smart provisioning request examples and allocation pools
- `docs/`
  - muxer and RPDB design notes
- `scripts/`
  - customer-scoped render and sync helpers
- `src/`
  - RPDB control-plane logic
- `runtime-package/`
  - future deployable muxer runtime root
  - this will become the package source used by the empty-platform and platform deploy flow

See:

- [MUXER3_RUNTIME_PORT_MAP.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/MUXER3_RUNTIME_PORT_MAP.md)
