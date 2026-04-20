# Resource Allocation Model

## Purpose

The RPDB platform needs to track not only customers, but also the reusable
platform namespaces that each customer consumes.

That includes resources such as:

- `fwmark`
- `route_table`
- `rpdb_priority`
- `tunnel_key`
- overlay address block
- transport interface name
- VTI interface name
- backend assignment

When a request indicates VTI usage, the allocator also derives the IPsec mark
from the allocated `fwmark` as `<fwmark>/0xffffffff`. The operator should not
hand-author this mark in the request.

Without explicit allocation tracking, provisioning has to guess what is free.
That does not scale safely.

## Core Idea

The database should answer these questions:

- what resource pools exist
- what values are available
- which customer owns each allocated value
- when it was allocated
- when it was released

The customer item describes the customer.

The allocation item describes the reusable platform resources consumed by that
customer.

One important refinement:

- **exclusive namespaces** should be reserved one owner at a time
- **shared placement fields** should still be tracked, but not treated as
  collision errors

## Smart Reservation Rule

Reservations should be smart.

That means provisioning should not expect operators to hand-pick values like:

- `fwmark`
- `route_table`
- `rpdb_priority`
- `tunnel_key`
- overlay block
- interface names
- backend assignment slot

Instead, the operator should provide the normal site-to-site VPN inputs and the
platform should reserve the required namespaces automatically, then track their
ownership in the database.

The target operator-facing contract is described in:

- [PROVISIONING_INPUT_MODEL.md](/muxer/docs/PROVISIONING_INPUT_MODEL.md)

## What Must Be Tracked

### Customer record

The customer record should continue to store:

- `customer_id`
- `customer_name`
- `customer_class`
- `backend_cluster`
- `backend_assignment`
- `backend_role`
- `customer_json`

### Allocation record

Each customer should also have tracked allocations for:

- `fwmark`
- `route_table`
- `rpdb_priority`
- `tunnel_key`
- `overlay_block`
- `transport_interface_name`
- `vti_interface_name`

These are the fields that should be treated as exclusive reservations.

The customer record should also track shared placement values such as:

- `backend_assignment`
- `backend_role`

Those values matter for placement and auditability, but they are not treated as
one-owner-only collision slots.

## Example Allocation Values

### Non-NAT customer example

- `customer_name`: `legacy-cust0003`
- `fwmark`: `0x2003`
- `route_table`: `2003`
- `rpdb_priority`: `1003`
- `tunnel_key`: `1003`
- `overlay_block`: `169.254.0.8/30`
- `transport_interface_name`: `gre-cust-0003`
- `vti_interface_name`: `vti-lcg0003`
- `backend_assignment`: `nonnat-pool-01`

### NAT customer example

- `customer_name`: `vpn-customer-stage1-15-cust-0003`
- `fwmark`: `0x41003`
- `route_table`: `41003`
- `rpdb_priority`: `11003`
- `tunnel_key`: `41003`
- `overlay_block`: `169.254.60.8/30`
- `transport_interface_name`: `gre-vpn-0003`
- `vti_interface_name`: `vti-vpn0003`
- `backend_assignment`: `nat-pool-01`

## Resource Pools

The system should define pools for each allocatable namespace.

Examples:

- `fwmark.nat`
- `fwmark.non-nat`
- `route_table.nat`
- `route_table.non-nat`
- `rpdb_priority.customer`
- `tunnel_key.gre`
- `overlay.gre`
- `transport_interface.gre`
- `vti_interface.shared`
- `backend_assignment.nat`
- `backend_assignment.non-nat`

Each pool should define:

- pool name
- resource type
- allocation scope
- allowed range or pattern
- reservation rules
- release rules

## Suggested Item Shapes

### Customer item

Key:

- `PK = CUSTOMER#<customer_name>`
- `SK = CURRENT`

Core fields:

- `customer_id`
- `customer_name`
- `customer_class`
- `backend_cluster`
- `backend_assignment`
- `backend_role`
- `schema_version`
- `updated_at`
- `customer_json`

### Resource allocation item

Current repo implementation uses a simpler exclusive-claim shape:

- `resource_key = <resource_type>#<resource_value>` as the primary key

Core fields:

- `resource_key`
- `resource_type`
- `resource_value`
- `pool_name`
- `customer_name`
- `customer_id`
- `customer_class`
- `status`
- `allocated_at`
- `source_ref`
- `exclusive`

Example:

- `resource_key = fwmark#0x2000`

This shape is implemented in:

- [allocation_sot.py](/muxer/src/muxerlib/allocation_sot.py)

## Provisioning Workflow

Normal new-customer provisioning should work like this:

1. validate the customer request
2. determine which pools apply
3. reserve required resources from those pools
4. write customer item with the resolved allocations
5. write exclusive resource allocation ownership items
6. render runtime artifacts from the resolved allocations
7. apply the customer

Dynamic NAT-T promotion is a reviewed replacement flow:

1. provision the initial customer from non-NAT pools
2. observe UDP/4500 from the same peer
3. process the observation through the repo-only audited workflow
4. generate a NAT promotion request and promoted allocation package
5. provision the promoted request from NAT pools while ignoring the old
   same-name package during planning
6. reprocess the same observation to verify it returns the existing audit
   instead of allocating again
7. review old and new allocation summaries side by side
8. keep old allocations reserved until the live promotion succeeds or rollback
   ownership says they can be released

The `--replace-customer` flag is not a live release operation. It only prevents
the same customer name from blocking the repo-only replacement allocation plan.
The audited observation processor applies that same planning rule internally
and records an idempotency key so duplicate UDP/4500 events do not create
duplicate staged allocations.

Normal delete should work like this:

1. load the customer item
2. remove customer runtime state
3. mark owned allocations as released
4. delete or archive the customer item

## Collision Prevention

Provisioning should not infer the "next free" resource from files.

It should reserve the resource in DynamoDB with conditional writes so that two
provisioning operations cannot claim the same resource at the same time.

This is especially important for:

- `fwmark`
- `route_table`
- `rpdb_priority`
- `overlay_block`
- interface names

## Relationship To Growth

This model is what allows the platform to grow safely.

It gives us:

- explicit ownership
- collision prevention
- release tracking
- auditability
- predictable per-customer provisioning

Without it, the customer model may be clean, but the provisioning layer is
still fragile.

## Near-Term Implementation Plan

1. define the allocation item schema
2. define the resource pools
3. add validation that checks for collisions in planned allocations
4. add allocation-aware provisioning helpers
5. use resolved allocations when building the customer runtime record

## Migration Gate

Before large-scale onboarding, the RPDB control plane should be able to prove:

- who owns every `fwmark`
- who owns every `route_table`
- who owns every `rpdb_priority`
- who owns every overlay block
- who owns every customer transport interface name
- who owns each backend assignment

In the current repo implementation:

- exclusive resources are what must be reserved collision-free
- shared placement values are tracked in the customer record and allocation
  summary, but they are not enforced as one-owner-only claims
