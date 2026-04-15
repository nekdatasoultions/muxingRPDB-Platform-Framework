# RPDB Runtime Completion Plan

## Purpose

This document tracks the runtime work that still has to be finished before the
RPDB muxer can be treated as customer-scoped and migration-ready.

The framework, customer model, and SoT shape already point in the right
direction. The remaining gap is the runtime control plane and dataplane apply
path.

## What Is Already Fixed

- explicit `rpdb_priority` support exists in the runtime
- one item per customer is the canonical DynamoDB model
- the customer source and render flow are customer-scoped by design
- logical backend placement is now separated from physical environment
  resolution

This means the old implicit-priority control-plane ceiling is no longer the
main blocker.

## Current Runtime Gaps

### 1. Normal DynamoDB loading still scans the whole table

Current behavior lives in:

- `muxer/runtime-package/src/muxerlib/dynamodb_sot.py`

Today `load_customer_modules_from_dynamodb()` calls `_scan_items()` and reads
every item in the table.

That is acceptable for:

- explicit fleet inventory
- admin/export tasks

It is not the right default for:

- onboarding one customer
- removing one customer
- validating one customer

### 2. The muxer CLI is still fleet-oriented

Current behavior lives in:

- `muxer/runtime-package/src/muxerlib/cli.py`

Today the runtime CLI only exposes:

- `apply`
- `flush`
- `show`
- `render-ipsec`

There is not yet a real runtime command surface for:

- `show-customer`
- `apply-customer`
- `remove-customer`

### 3. Normal apply still rebuilds full chains

Current behavior lives in:

- `muxer/runtime-package/src/muxerlib/modes.py`

In both pass-through and termination modes, the runtime currently:

- flushes the active chains
- loops over the full module list
- rebuilds policy/tunnel/firewall state for all loaded modules

That is the main reason customer onboarding/removal is still more fleet-like
than it should be.

### 4. The dataplane is still linear iptables programming

Current behavior lives in:

- `muxer/runtime-package/src/muxerlib/modes.py`
- `muxer/runtime-package/src/muxerlib/core.py`

The runtime still issues many individual `iptables` and `ip` commands and builds
linear rule sets.

That is workable for small scale and lab use, but it is not the final scaling
shape for growth well beyond current fleet sizes.

## Target Runtime Behavior

The target runtime should behave like this:

1. Normal customer operations use one customer key at a time.
2. Fleet scans exist, but only as explicit admin actions.
3. Normal customer add/remove/update uses delta apply.
4. Delta apply updates only the affected customer state.
5. Dataplane updates are batched and move toward `nftables` sets/maps.

## Implementation Sequence

### Phase 1. Customer-scoped SoT operations

Add runtime helpers for:

- `get-item` by `customer_name`
- `put-item` by `customer_name`
- `delete-item` by `customer_name`

Keep table scan only for explicit fleet workflows.

### Phase 2. Customer-scoped runtime commands

Add runtime commands for:

- `show-customer`
- `apply-customer`
- `remove-customer`

The default operator path should become one customer at a time.

Current status:

- `show-customer` is implemented
- `apply-customer` is implemented for pass-through mode
- `remove-customer` is implemented for pass-through mode
- termination mode still needs its customer-scoped command path

### Phase 2.5. Resource allocation tracking

Add DB-backed tracking for reusable namespaces such as:

- `fwmark`
- `route_table`
- `rpdb_priority`
- `tunnel_key`
- overlay block
- transport interface name
- VTI interface name
- backend assignment

The allocation model and examples live in:

- [RESOURCE_ALLOCATION_MODEL.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/RESOURCE_ALLOCATION_MODEL.md)

This is a growth requirement, not an optional cleanup item. Provisioning should
reserve and release these resources explicitly instead of inferring "next free"
values from files or rendered state.

The target provisioning contract should be operator-light:

- operators provide normal site-to-site inputs plus customer name and class
- the platform allocates namespace-heavy transport/runtime fields automatically

That contract is documented in:

- [PROVISIONING_INPUT_MODEL.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/PROVISIONING_INPUT_MODEL.md)

### Phase 3. Delta dataplane apply

Refactor the runtime so normal customer changes do not require:

- full chain flush
- full module reload
- full tunnel/rule rebuild

This is the minimum migration gate before real customer swing work.

Current status:

- pass-through customer apply/remove now clears and reapplies only the selected
  customer's runtime state
- fleet `apply` still exists and still rebuilds the full loaded module set
- termination mode still needs equivalent customer-scoped delta behavior

### Phase 4. Scalable dataplane backend

Add a batching layer and then move toward:

- `nftables`
- sets/maps
- fewer linear rule walks

This is the path that makes the RPDB runtime materially better at larger fleet
sizes.

## Migration Gate

Do not treat the RPDB runtime as migration-ready until all of these are true:

- normal customer operations do not depend on DynamoDB full-table scan
- a single customer can be applied without rebuilding all customers
- a single customer can be removed without rebuilding all customers
- the dataplane update path is at least delta-based, even if `nftables`
  migration is still in progress

## Exit Criteria

We can call this runtime complete enough for migration when we can prove:

1. one customer can be added with a customer-scoped command
2. one customer can be removed with a customer-scoped command
3. existing customer state is left untouched by that operation
4. runtime no longer depends on normal fleet scan for those operations
5. isolated-platform verification passes before any production swing
