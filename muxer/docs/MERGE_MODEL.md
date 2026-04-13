# Merge Model

## Goal

The RPDB framework should treat the customer source file as the smallest
authoring unit, while still keeping shared defaults and class defaults in one
place.

## Layers

Each merged customer module is built in this order:

1. shared defaults from `customer-defaults/defaults.yaml`
2. class overrides from `customer-defaults/classes/<class>.yaml`
3. customer source overrides from `customer-sources/<customer>/customer.yaml`

Later layers win.

## Result Shape

The merged module is expected to contain:

```text
schema_version
customer
peer
transport
selectors
backend
protocols
natd_rewrite
ipsec
post_ipsec_nat
metadata
```

## RPDB Priority Resolution

The merged module should always end with an explicit
`transport.rpdb_priority`.

Resolution order:

1. `customer.transport.rpdb_priority`
2. `defaults.rpdb.priority_base + customer.id`

## Why This Matters

This gives us:

- one file per customer
- low-blast-radius customer edits
- explicit RPDB behavior
- a canonical merged record ready for DynamoDB and rendering
