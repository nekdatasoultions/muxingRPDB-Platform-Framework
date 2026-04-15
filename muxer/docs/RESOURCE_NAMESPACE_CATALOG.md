# Resource Namespace Catalog

## Purpose

This catalog lists the customer-scoped fields that matter most for growth.

These are the values that either:

- must stay unique to avoid dataplane collisions, or
- must be tracked consistently so the platform knows where a customer is placed
  and what namespace values were consumed

## Identity Fields

These are core identity keys, not allocator pools.

| Field | Purpose | Example | Uniqueness Scope | Collision Risk |
| --- | --- | --- | --- | --- |
| `customer_name` | Stable human/customer key | `legacy-cust0003` | global | high |
| `customer_id` | Stable numeric customer key | `2000` | global | high |
| `customer_class` | Service shape and protocol profile | `strict-non-nat` | not unique | low |
| `backend_cluster` | Logical pool family | `non-nat` | not unique | low |

## Exclusive Namespace Fields

These are allocator-owned and must remain unique.

| Field | Purpose | Example | Uniqueness Scope | Collision Risk |
| --- | --- | --- | --- | --- |
| `fwmark` | Customer-specific steering mark on the muxer | `0x2000` | global | very high |
| `route_table` | Customer-specific route table | `2000` | global | very high |
| `rpdb_priority` | Customer-specific policy-routing priority | `1000` | global | very high |
| `tunnel_key` | GRE key / transport identity slot | `2000` | global | high |
| `overlay_block` | Customer overlay /30 block | `169.254.0.0/30` | global | high |
| `transport_interface` | Customer transport interface name | `gre-cust-2000` | global | high |
| `vti_interface` | VTI interface name when VTI is used | `vti-cust2000` | global | high |

## Shared Placement Fields

These are tracked, but they are not one-owner-only reservation slots.

| Field | Purpose | Example | Uniqueness Scope | Collision Risk |
| --- | --- | --- | --- | --- |
| `backend_assignment` | Logical shard/group placement | `nonnat-pool-01` | shared | medium |
| `backend_role` | Active logical runtime role | `nonnat-active` | shared | medium |

## Why This Matters

Normal VPN systems mostly track:

- peer
- selectors
- crypto settings

The RPDB platform also has to track:

- steering namespace
- overlay namespace
- interface namespace
- backend placement

That is the part that lets us:

- grow without accidental reuse of marks, tables, and priorities
- provision one customer at a time safely
- know exactly what a delete should release
- know which pool/shard currently owns a customer

## Related Docs

- [PROVISIONING_INPUT_MODEL.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/PROVISIONING_INPUT_MODEL.md)
- [RESOURCE_ALLOCATION_MODEL.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/RESOURCE_ALLOCATION_MODEL.md)
- [RUNTIME_COMPLETION_PLAN.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/RUNTIME_COMPLETION_PLAN.md)
