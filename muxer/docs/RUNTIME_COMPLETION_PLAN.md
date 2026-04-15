# RPDB Runtime Completion Plan

## Purpose

This document now tracks the completion state of the runtime work required to
make the RPDB muxer customer-scoped and migration-ready for the pass-through
architecture.

The framework, customer model, and SoT shape are now matched by a customer-
scoped runtime path, an allocator-backed provisioning path, and a repo-only
verification harness.

The next service-intent modeling step is tracked in:

- [VPN_SERVICE_INTENT_MODEL.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/VPN_SERVICE_INTENT_MODEL.md)

## What Is Already Fixed

- explicit `rpdb_priority` support exists in the runtime
- one item per customer is the canonical DynamoDB model
- the customer source and render flow are customer-scoped by design
- logical backend placement is now separated from physical environment
  resolution

This means the old implicit-priority control-plane ceiling is no longer the
main blocker.

## Current Runtime Boundaries

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

### 2. The muxer CLI is only partially customer-scoped outside pass-through

Current behavior lives in:

- `muxer/runtime-package/src/muxerlib/cli.py`

Pass-through mode now has:

- `show-customer`
- `apply-customer`
- `remove-customer`

Termination mode is intentionally blocked for those customer-scoped write
commands because it is not part of the current migration target.

### 3. Fleet apply still rebuilds full chains

Current behavior lives in:

- `muxer/runtime-package/src/muxerlib/modes.py`

The explicit fleet `apply` path still:

- flushes the active chains
- loops over the full module list
- rebuilds policy/tunnel/firewall state for all loaded modules

That is acceptable as an explicit fleet command, but it is no longer the normal
customer-by-customer path for pass-through mode.

### 4. The live dataplane still includes legacy linear programming

Current behavior lives in:

- `muxer/runtime-package/src/muxerlib/modes.py`
- `muxer/runtime-package/src/muxerlib/core.py`

The live path still contains legacy per-customer `iptables` and `ip`
programming for translation and bridge behavior.

The repo now has the first batched `nftables` render path, but that render path
is not yet the live apply backend.

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

Current status:

- completed

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
- termination mode is intentionally blocked and documented as out of migration
  scope

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
- [RESOURCE_NAMESPACE_CATALOG.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/RESOURCE_NAMESPACE_CATALOG.md)

Current status:

- completed in repo code and docs
- minimal provisioning requests now expand into fully allocated compatibility
  customer sources
- exclusive allocation DDB item shapes are now generated in the repo-only
  provisioning flow

### Phase 2.6. VPN service intent and richer post-IPsec NAT intent

Extend the customer-side intent model so operators provide:

- VPN compatibility and interoperability behavior
- interesting traffic intent
- richer post-IPsec NAT translation intent

That includes explicit modeling for:

- IKE version choice
- replay-protection policy
- DF-bit handling policy
- richer multi-policy compatibility structure
- block-preserving one-to-one translated subnet mapping
- explicit `/32` to `/32` host mappings inside a translated pool

These belong to the customer service model, not the allocator-owned namespace
layer.

Current status:

- schema and parser support completed
- richer customer request validation now accepts the new service-intent fields
- render/export carry-through completed for the head-end artifact bundle
- head-end validation now checks the richer `swanctl` and post-IPsec NAT
  render output
- repo-only verification covers valid one-to-one and explicit host-mapping
  provisioning, bundle validation, staged head-end install, staged validation,
  and staged removal
- invalid explicit host mappings are rejected by the parser/provisioning path

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
- termination mode is intentionally blocked for customer-scoped writes
- repo-only verification proves the pass-through customer path does not flush
  the whole chain set

### Phase 4. Scalable dataplane backend

Add a batching layer and then move toward:

- `nftables`
- sets/maps
- fewer linear rule walks

This is the path that makes the RPDB runtime materially better at larger fleet
sizes.

Current status:

- the first batched `nftables` render path exists in:
  - [nftables.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/runtime-package/src/muxerlib/nftables.py)
  - [render_nft_passthrough.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/runtime-package/scripts/render_nft_passthrough.py)
- this layer currently covers peer classification, fwmark maps, and default
  drop render
- live DNAT/SNAT rewrite and NFQUEUE bridge stages remain on the legacy
  per-customer path for now

## Migration Gate

Do not treat the RPDB runtime as migration-ready until all of these are true:

- normal customer operations do not depend on DynamoDB full-table scan
- a single customer can be applied without rebuilding all customers
- a single customer can be removed without rebuilding all customers
- the dataplane update path is at least delta-based, even if `nftables`
  migration is still in progress

Current status for the pass-through migration target:

- met in repo-only verification

## Exit Criteria

We can call this runtime complete enough for pass-through migration when we can
prove:

1. one customer can be added with a customer-scoped command
2. one customer can be removed with a customer-scoped command
3. existing customer state is left untouched by that operation
4. runtime no longer depends on normal fleet scan for those operations
5. isolated-platform verification passes before any production swing

## Repo-Only Verification

The repo-only completion proof now lives in:

- [run_repo_verification.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/scripts/run_repo_verification.py)

And the generated summary lives in:

- [repo-verification-summary.json](/E:/Code1/muxingRPDB%20Platform%20Framework-main/build/repo-verification/repo-verification-summary.json)

That verifier proves:

- minimal customer requests validate
- smart allocation expands them into full customer records
- allocation DDB items are generated for exclusive namespaces
- pass-through runtime can load one customer
- pass-through `apply-customer` and `remove-customer` stay delta-oriented
- termination mode remains explicitly blocked
- the first batched `nftables` render path works repo-only
- richer VPN service intent renders into head-end artifacts
- one-to-one netmap and explicit host-map NAT examples stage and remove cleanly
