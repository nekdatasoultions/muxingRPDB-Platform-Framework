# Muxer

This directory will hold the RPDB-based muxer control plane and customer model.

The intent is to make the muxer workflow customer-scoped by default:

- source one customer
- sync one customer
- render one customer
- apply one customer

Subdirectories:

- `config/`
  - customer defaults and per-customer sources
- `docs/`
  - muxer and RPDB design notes
- `scripts/`
  - customer-scoped render and sync helpers
- `src/`
  - future muxer library and control-plane logic
