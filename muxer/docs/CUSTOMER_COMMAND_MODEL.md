# Customer Command Model

## Goal

The RPDB platform should be customer-scoped by default.

That means operators should work on one customer unless they intentionally ask
for a fleet-wide action.

## Default Commands

The intended default commands are:

- `sync-customer`
- `render-customer`
- `validate-customer`
- `apply-customer`
- `rollback-customer`

The first scaffold scripts align to that model:

- `validate_customer_source.py`
- `build_customer_item.py`
- `render_customer_artifacts.py`
- `validate_rendered_artifacts.py`

## Fleet Commands

Fleet commands should still exist, but they should be explicit:

- `sync-all-customers`
- `render-all-customers`
- `validate-all-customers`

## Why This Matters

This reduces:

- blast radius
- unnecessary full-fleet work
- customer onboarding latency
- avoidable DynamoDB full-table access

## Future Script Shape

The exact command names can still change, but the workflow should stay:

1. source one customer
2. merge defaults
3. validate
4. sync one item to DynamoDB
5. render one customer
6. apply one customer
