# Provisioning Input Model

## Goal

Customer provisioning should be operator-light and allocator-heavy.

That means the operator should provide the normal site-to-site VPN details and
the platform should allocate the reusable RPDB/runtime namespaces
automatically.

## Operator Input

The target operator input should be limited to:

- `customer_name`
- peer/public VPN details
  - peer public IP
  - peer remote ID if needed
  - PSK secret reference
- traffic selectors
  - local subnets
  - remote subnets
- optional logical placement override
  - backend assignment preference when the platform should not choose it
- optional feature flags
  - NAT-D rewrite
  - disabling dynamic NAT-T promotion when UDP/4500 must not auto-promote
  - post-IPsec NAT
  - VTI usage if required by the customer type

This input layer should also own the VPN service and interoperability knobs
that describe how the customer connection must behave, including:

- IKEv1 vs IKEv2
- allowed crypto policy sets
- DPD behavior
- replay protection policy
- PFS flexibility and required-group behavior
- fragmentation and force-encapsulation behavior
- DF-bit handling default
- whether VTI is required
- what customer-side traffic is interesting for the VPN
- what traffic is translated after IPsec, including `/27` one-to-one mapping
  intent or explicit `/32` to `/32` mappings

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

These are allocator concerns because they are collision-prone platform
namespaces, not customer service intent.

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

The customer-provided service intent versus allocator-owned namespace split is
tracked in:

- [VPN_SERVICE_INTENT_MODEL.md](VPN_SERVICE_INTENT_MODEL.md)

### Target state

The target state is:

- those fields become allocator-owned by default
- customer source files do not have to hand-author them
- provisioning resolves them automatically from tracked pools

## Current Repo Implementation

The repo now has a working minimal-request provisioning path through:

- [customer-request.schema.json](../config/schema/customer-request.schema.json)
- [defaults.yaml](../config/allocation-pools/defaults.yaml)
- [validate_customer_request.py](../scripts/validate_customer_request.py)
- [validate_customer_allocations.py](../scripts/validate_customer_allocations.py)
- [provision_customer_request.py](../scripts/provision_customer_request.py)
- [plan_nat_t_promotion.py](../scripts/plan_nat_t_promotion.py)
- [process_nat_t_observation.py](../scripts/process_nat_t_observation.py)
- [provision_customer_end_to_end.py](../scripts/provision_customer_end_to_end.py)
- [watch_nat_t_logs.py](../scripts/watch_nat_t_logs.py)
- [prepare_customer_pilot.py](../scripts/prepare_customer_pilot.py)

That path now:

- validates the minimal request
- accepts richer VPN compatibility intent and richer post-IPsec NAT intent in
  the request schema
- checks existing customer sources for exclusive namespace collisions
- allocates transport/runtime namespace values automatically
- emits a fully allocated compatibility customer source
- emits the merged customer module and customer SoT item
- emits the exclusive allocation DDB item view
- can produce a repo-only NAT-T promotion request when a dynamic strict
  non-NAT customer is later observed on UDP/4500
- can process the UDP/4500 observation through an idempotent audit workflow so
  repeat observations return the existing staged package instead of allocating
  again
- exposes a one-file operator entrypoint where the normal command is
  `python muxer\scripts\provision_customer_end_to_end.py <customer-request.yaml>`
- can watch muxer logs, detect UDP/500 followed by UDP/4500 for a dynamic
  customer peer, and automatically create the NAT-T observation/package
- can wrap the repo-only request, allocation, render, handoff, bundle,
  validation, staged head-end, and readiness checks into one pilot review
  package

## Dynamic NAT-T Promotion Input

When customer NAT behavior is unknown, the safe default request starts as
strict non-NAT without the operator declaring the stack:

- omit `customer_class`
- omit `backend.cluster`
- `protocols.udp500: true`
- `protocols.udp4500: false`
- `protocols.esp50: true`

If the muxer later observes UDP/4500 from that same peer, the dynamic
provisioning processor can generate a reviewed NAT-T promotion package. This
package changes the customer class to `nat`, enables UDP/4500, uses NAT
allocation pools, and writes an audit record proving `live_apply: false`.

Explicit `customer_class` and `backend.cluster` remain supported for static
compatibility examples and migrations, but the normal onboarding path should
let the workflow select strict non-NAT first and promote only when observed
traffic proves NAT-T is needed.

The committed example is:

- [example-dynamic-default-nonnat.yaml](../config/customer-requests/examples/example-dynamic-default-nonnat.yaml)

The detailed model is documented in:

- [DYNAMIC_NAT_T_PROVISIONING.md](DYNAMIC_NAT_T_PROVISIONING.md)

## Example Minimal Non-NAT Input

```yaml
schema_version: 1

customer:
  name: legacy-cust0003
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
```

The allocator should then derive and reserve values such as:

- `customer_id = 2003`
- `fwmark = 0x2003`
- `route_table = 2003`
- `rpdb_priority = 1003`
- `tunnel_key = 1003`
- `overlay_block = 169.254.0.8/30`
- `transport_interface_name = gre-cust-0003`

## Example NAT-T Promotion Input

The operator does not pre-build a NAT request for the normal workflow. The
operator provides the same customer request shape as above, and the muxer-side
observation feed provides the NAT-T trigger:

```json
{
  "schema_version": 1,
  "customer_name": "vpn-customer-stage1-15-cust-0004",
  "observed_peer": "3.237.201.84",
  "observed_protocol": "udp",
  "observed_dport": 4500,
  "initial_udp500_observed": true,
  "packet_count": 1
}
```

The NAT-T promotion workflow should then derive and reserve values such as:

- `customer_id = 41003`
- `fwmark = 0x41003`
- `route_table = 41003`
- `rpdb_priority = 11003`
- `tunnel_key = 41003`
- `overlay_block = 169.254.60.8/30`
- `transport_interface_name = gre-vpn-0003`

## Example Service-Intent NAT Inputs

The repo also carries committed examples for the richer VPN compatibility and
post-IPsec NAT intent:

- [example-service-intent-netmap.yaml](../config/customer-requests/examples/example-service-intent-netmap.yaml)
- [example-service-intent-explicit-host-map.yaml](../config/customer-requests/examples/example-service-intent-explicit-host-map.yaml)

Those examples show:

- IKE version selection
- multiple IKE and ESP policy options
- DPD behavior
- replay protection
- PFS intent
- force-encapsulation, MOBIKE, fragmentation, and DF-bit behavior
- `/27` one-to-one netmap translation
- explicit `/32` to `/32` host translation inside a `/27` translated pool

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

## Important Boundary

The provisioning layer should not own the VPN behavior contract itself.

Customer-provided:

- VPN compatibility and interoperability behavior
- interesting traffic definition
- post-IPsec NAT behavior and translation intent

Allocator-provided:

- marks
- tables
- RPDB priorities
- tunnel keys
- GRE or VTI names
- overlay addressing
- backend slot resolution

## Migration Gate

Before migration at scale, the platform should support a mode where:

- manually authored transport namespace fields are optional
- allocator-generated values become the default path
