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

- `validate_customer_request.py`
- `validate_customer_allocations.py`
- `provision_customer_request.py`
- `validate_customer_source.py`
- `build_customer_item.py`
- `render_customer_artifacts.py`
- `validate_rendered_artifacts.py`
- `validate_environment_bindings.py`
- `bind_rendered_artifacts.py`
- `validate_bound_artifacts.py`

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

## Current Runtime Status

The target model above is still ahead of the runtime implementation.

Today the runtime still has two important fleet-style behaviors:

- explicit fleet inventory against DynamoDB still uses table scan
- apply still flushes and rebuilds the active chains for the loaded module set

The first safe customer-scoped runtime read path now exists:

- `show-customer`

The first safe customer-scoped pass-through write paths now also exist:

- `apply-customer`
- `remove-customer`

Current boundary:

- customer-scoped commands now refuse DynamoDB fleet-scan fallback
- these customer-scoped write commands are implemented for pass-through mode
- termination mode is intentionally blocked for customer-scoped writes
- `apply` remains the explicit fleet-style command
- explicit fleet scan still exists for admin and inventory workflows

That gives us a real one-customer path for the migration architecture we are
actually using.

The completion checklist for closing that gap lives in:

- [RUNTIME_COMPLETION_PLAN.md](./RUNTIME_COMPLETION_PLAN.md)
- [RUNTIME_MODE_BOUNDARIES.md](./RUNTIME_MODE_BOUNDARIES.md)
- [SCALE_BASELINE_HARNESS.md](./SCALE_BASELINE_HARNESS.md)
