# DynamoDB Item Model

## Purpose

This document defines the per-customer DynamoDB item shape for the RPDB model.

The DynamoDB item is the canonical runtime customer record. It should be the
result of merging:

1. shared defaults
2. class defaults
3. customer source file

## One Item Per Customer

The intended access pattern is one item per customer.

Normal operations should prefer:

- `get-item`
- `put-item`

Normal customer workflows should not depend on full-table `scan` operations.

## Core Fields

Each item should contain:

- `customer_name`
- `customer_id`
- `customer_class`
- `peer_ip`
- `fwmark`
- `route_table`
- `rpdb_priority`
- `backend_role`
- `backend_underlay_ip`
- `source_ref`
- `schema_version`
- `updated_at`
- `customer_json`

## Why Store `customer_json`

The `customer_json` field should hold the canonical merged customer module so
renderers and operators can consume a stable runtime record without repeating
the defaults merge everywhere.

The merged module should include the resolved sections we expect the control
plane to consume directly:

- `customer`
- `peer`
- `transport`
- `selectors`
- `backend`
- `protocols`
- `natd_rewrite`
- `ipsec`
- `post_ipsec_nat`
- `metadata`

## Why Store Routing Fields Separately

The top-level item also stores:

- `fwmark`
- `route_table`
- `rpdb_priority`

That makes it easier to:

- inspect customers operationally
- query or export useful routing metadata
- validate priority and table allocation without fully parsing `customer_json`

## Secret Handling

The DynamoDB item should carry the merged customer module, but the repo and
source file should still reference secrets indirectly.

`customer_json` may include the secret reference path. It should not include the
resolved PSK value.

## Validation Target

The machine-readable schema for this item lives at:

- [customer-ddb-item.schema.json](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/config/schema/customer-ddb-item.schema.json)
