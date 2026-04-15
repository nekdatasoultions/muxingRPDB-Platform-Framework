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
- `backend_assignment`

Not every customer will use every field, but the allocation model should still
handle them consistently.

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

Key:

- `PK = RESOURCE#<resource_type>#<resource_value>`
- `SK = OWNER#<customer_name>`

Core fields:

- `resource_type`
- `resource_value`
- `pool_name`
- `customer_name`
- `customer_id`
- `status`
- `allocated_at`
- `released_at`
- `source_ref`

Example:

- `PK = RESOURCE#fwmark#0x2003`
- `SK = OWNER#legacy-cust0003`

### Optional customer allocation index item

Key:

- `PK = CUSTOMER#<customer_name>`
- `SK = RESOURCE#<resource_type>#<resource_value>`

This makes it easy to list all resources owned by one customer without scanning.

## Provisioning Workflow

Normal new-customer provisioning should work like this:

1. validate the customer request
2. determine which pools apply
3. reserve required resources from those pools
4. write customer item with the resolved allocations
5. write resource allocation ownership items
6. render runtime artifacts from the resolved allocations
7. apply the customer

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
