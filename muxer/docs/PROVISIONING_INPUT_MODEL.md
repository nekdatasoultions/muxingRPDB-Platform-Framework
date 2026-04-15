# Provisioning Input Model

## Goal

Customer provisioning should be operator-light and allocator-heavy.

That means the operator should provide the normal site-to-site VPN details and
the platform should allocate the reusable RPDB/runtime namespaces
automatically.

## Operator Input

The target operator input should be limited to:

- `customer_name`
- `customer_class`
  - `nat`
  - `strict-non-nat`
- peer/public VPN details
  - peer public IP
  - peer remote ID if needed
  - PSK secret reference
- traffic selectors
  - local subnets
  - remote subnets
- logical placement
  - backend cluster
  - optional backend assignment preference
- optional feature flags
  - NAT-D rewrite
  - post-IPsec NAT
  - VTI usage if required by the customer type

In other words, the operator should describe the customer and the desired
service shape, not hand-allocate platform namespaces.

## Auto-Assigned By The Platform

The provisioning layer should allocate and track:

- `customer_id`
- `fwmark`
- `route_table`
- `rpdb_priority`
- `tunnel_key`
- overlay address block
- transport interface name
- VTI interface name
- backend assignment
- resolved backend role

These values should come from tracked pools and should be written back into the
canonical customer runtime record after allocation.

## Why This Matters

This prevents operators from needing to manually manage:

- collision-prone marks
- route table IDs
- RPDB priority bands
- tunnel interface naming
- overlay slot selection
- backend placement drift

It also makes onboarding consistent for:

- true new customers
- migrated legacy customers

## Current Versus Target

### Current compatibility state

The current compatibility schema still allows customer source files to carry
fields such as:

- `transport.mark`
- `transport.table`
- `transport.tunnel_key`
- `transport.interface`
- `transport.overlay`
- `transport.rpdb_priority`

That keeps the framework compatible while the allocator layer is being built.

### Target state

The target state is:

- those fields become allocator-owned by default
- customer source files do not have to hand-author them
- provisioning resolves them automatically from tracked pools

## Current Repo Implementation

The repo now has a working minimal-request provisioning path through:

- [customer-request.schema.json](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/config/schema/customer-request.schema.json)
- [defaults.yaml](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/config/allocation-pools/defaults.yaml)
- [validate_customer_request.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/scripts/validate_customer_request.py)
- [validate_customer_allocations.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/scripts/validate_customer_allocations.py)
- [provision_customer_request.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/scripts/provision_customer_request.py)

That path now:

- validates the minimal request
- checks existing customer sources for exclusive namespace collisions
- allocates transport/runtime namespace values automatically
- emits a fully allocated compatibility customer source
- emits the merged customer module and customer SoT item
- emits the exclusive allocation DDB item view

## Example Minimal Non-NAT Input

```yaml
schema_version: 1

customer:
  name: legacy-cust0003
  customer_class: strict-non-nat
  peer:
    public_ip: 166.213.153.41
    psk_secret_ref: /muxingrpdb/customers/legacy-cust0003/psk
  selectors:
    local_subnets:
      - 172.31.54.39/32
      - 194.138.36.80/28
      - 172.30.0.90/32
    remote_subnets:
      - 10.129.4.12/32
  backend:
    cluster: non-nat
    assignment: nonnat-pool-01
```

The allocator should then derive and reserve values such as:

- `customer_id = 2003`
- `fwmark = 0x2003`
- `route_table = 2003`
- `rpdb_priority = 1003`
- `tunnel_key = 1003`
- `overlay_block = 169.254.0.8/30`
- `transport_interface_name = gre-cust-0003`

## Example Minimal NAT Input

```yaml
schema_version: 1

customer:
  name: vpn-customer-stage1-15-cust-0003
  customer_class: nat
  peer:
    public_ip: 198.51.100.25
    psk_secret_ref: /muxingrpdb/customers/vpn-customer-stage1-15-cust-0003/psk
  selectors:
    local_subnets:
      - 10.20.30.0/24
    remote_subnets:
      - 10.99.0.0/24
  backend:
    cluster: nat
    assignment: nat-pool-01
```

The allocator should then derive and reserve values such as:

- `customer_id = 41003`
- `fwmark = 0x41003`
- `route_table = 41003`
- `rpdb_priority = 11003`
- `tunnel_key = 41003`
- `overlay_block = 169.254.60.8/30`
- `transport_interface_name = gre-vpn-0003`

## Provisioning Contract

The provisioning path should work like this:

1. operator supplies the minimal customer request
2. validator checks required VPN and selector inputs
3. allocator reserves required platform namespaces
4. merged runtime customer record is built from:
   - operator input
   - class defaults
   - shared defaults
   - allocated namespace values
5. customer item and allocation items are written to the database
6. runtime artifacts are rendered from the resolved record

## Migration Gate

Before migration at scale, the platform should support a mode where:

- manually authored transport namespace fields are optional
- allocator-generated values become the default path
