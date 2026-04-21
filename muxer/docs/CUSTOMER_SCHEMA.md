# Customer Schema

## Purpose

This document defines the concrete customer source shape for the RPDB model.

The customer source file is the authoring record. It is not the final rendered
customer module. It is the input that gets merged with shared defaults and
class defaults before it is written to DynamoDB and rendered into customer
artifacts.

Important design direction:

- the customer source should describe the customer and service intent
- the provisioning layer should allocate platform namespaces automatically

That intent split is tracked in:

- [VPN_SERVICE_INTENT_MODEL.md](VPN_SERVICE_INTENT_MODEL.md)

The target operator-facing contract is described in:

- [PROVISIONING_INPUT_MODEL.md](PROVISIONING_INPUT_MODEL.md)

## File Location

Each customer should live at:

```text
muxer/config/customer-sources/<customer-name>/customer.yaml
```

## Top-Level Shape

```yaml
schema_version: 1

customer:
  id: 101
  name: example-nat-0001
  customer_class: nat
  peer: ...
  transport: ...
  selectors: ...
  backend: ...
  protocols: ...
  natd_rewrite: ...
  dynamic_provisioning: ...
  ipsec: ...
  post_ipsec_nat: ...
```

## Required Fields

### `customer.id`

- integer
- unique customer identifier

### `customer.name`

- stable customer name used in generated artifacts and DynamoDB

### `customer.customer_class`

Supported values:

- `nat`
- `strict-non-nat`

### `customer.peer`

Required fields:

- `public_ip`
- `psk_secret_ref`

Optional:

- `remote_id`

### `customer.transport`

Required fields:

- `mark`
- `table`
- `tunnel_key`
- `interface`
- `overlay`

Optional:

- `tunnel_type`
- `tunnel_ttl`
- `rpdb_priority`

Current state:

- these fields are still accepted and used by the compatibility runtime

Target state:

- these fields should become allocator-owned by default
- the operator should not need to hand-assign them for normal provisioning

### `customer.selectors`

Required:

- `local_subnets`
- `remote_subnets`

Optional:

- `remote_host_cidrs`

`remote_host_cidrs` tracks the scoped customer-side CIDRs that are expected to
use the tunnel when `remote_subnets` is a broader or overlapping customer
encryption domain. The name is kept for compatibility, but entries may be `/32`
hosts or smaller CIDR blocks such as `/28`. Every entry must be contained by
one of the declared `remote_subnets`.

When `remote_host_cidrs` is present, generated head-end IPsec artifacts use it
as the effective remote traffic selector. That means `swanctl remote_ts` is
rendered from the scoped CIDRs instead of the broader `remote_subnets`.

### `customer.backend`

Optional section.

Useful fields:

- `cluster`
- `assignment`
- `role`
- `underlay_ip`

Recommended shape:

- `cluster` identifies the logical head-end pool, such as `nat` or `non-nat`
- `assignment` identifies the logical slot, such as `active-a`
- `role` remains useful as a stable compatibility label
- `underlay_ip` is transitional compatibility only and should not be the long-term primary input

If omitted, the class defaults should provide the backend role and cluster.

### `customer.protocols`

Optional per-customer protocol overrides:

- `udp500`
- `udp4500`
- `esp50`
- `force_rewrite_4500_to_500`

### `customer.natd_rewrite`

Optional per-customer NAT-D behavior overrides:

- `enabled`
- `initiator_inner_ip`

### `customer.dynamic_provisioning`

Optional repo-only promotion intent for customers that start as strict non-NAT
while NAT-T behavior is still unknown.

Supported mode:

- `nat_t_auto_promote`

The section records:

- initial class: `strict-non-nat`
- initial backend: `non-nat`
- trigger protocol: `udp`
- trigger destination port: `4500`
- promotion class: `nat`
- promotion backend: `nat`

This section does not apply live changes by itself. The promotion helper
generates a reviewed NAT request when UDP/4500 is observed from the same peer.

Detailed model:

- [DYNAMIC_NAT_T_PROVISIONING.md](DYNAMIC_NAT_T_PROVISIONING.md)

### `customer.ipsec`

Optional per-customer IPsec overrides:

- `auto`
- `ike_version`
- `local_id`
- `remote_id`
- `ike`
- `esp`
- `ike_policies`
- `esp_policies`
- `dpddelay`
- `dpdtimeout`
- `dpdaction`
- `ikelifetime`
- `lifetime`
- `replay_protection`
- `pfs_required`
- `pfs_groups`
- `forceencaps`
- `mobike`
- `fragmentation`
- `clear_df_bit`
- `mark`
- `vti_interface`
- `vti_routing`
- `vti_shared`
- `bidirectional_secret`
- `initiation`

`initiation` is the explicit tunnel bring-up contract. The default platform
intent is bidirectional:

```yaml
ipsec:
  initiation:
    mode: bidirectional
    headend_can_initiate: true
    customer_can_initiate: true
    traffic_can_start_tunnel: true
    bring_up_on_apply: true
    swanctl_start_action: trap|start
```

This means the generated head-end config installs traffic-trigger trap
policies and also actively initiates the CHILD_SA when the connection is
loaded. A customer can still initiate from their side because the generated
head-end connection is loaded as a responder with the customer peer address,
remote ID, PSK, and traffic selectors.

Current repo note:

- the schema and parser now model the richer compatibility fields above
- the head-end artifact render now carries the key compatibility fields into
  `ipsec-intent.json` and `swanctl-connection.conf`
- repo-only validation checks that rendered fields such as IKE version, policy
  lists, replay protection, DF-bit behavior, DPD, encapsulation, MOBIKE, and
  fragmentation are represented in the staged head-end bundle
- repo-only validation checks that bidirectional initiation renders
  `start_action = trap|start`, an initiation intent, and a head-end
  `swanctl --initiate --child` helper

### `customer.post_ipsec_nat`

Optional for the customer source, but when present it must include:

- `enabled`

Useful fields include:

- `mapping_strategy`
- `translated_subnets`
- `translated_source_ip`
- `real_subnets`
- `core_subnets`
- `host_mappings`
- `interface`
- `output_mark`
- `tcp_mss_clamp`
- `route_via`
- `route_dev`

Important meaning:

- `selectors.remote_subnets` defines what customer-side traffic is in-scope for
  the VPN
- `post_ipsec_nat.real_subnets` defines which real customer-side subnets are
  translated after IPsec
- `post_ipsec_nat.translated_subnets` defines the translated block, such as a
  `/27`, that we present after NAT
- `post_ipsec_nat.core_subnets` defines our side local/core reachability for
  that translated path

Target NAT intent:

- block-preserving one-to-one mapping for subnet-to-subnet netmap behavior
- explicit `/32` to `/32` host mappings inside a translated pool

Current repo note:

- one-to-one netmap intent renders deterministic nftables maps
- explicit host mappings render deterministic nftables `DNAT` and `SNAT` state
- staged head-end validation checks the expected command model before install

### `customer.outside_nat`

Optional for the customer source, but when present it must include:

- `enabled`

Use `outside_nat` when the real local/core network behind the VPN head end must
be presented to the customer as a different customer-selected subnet.

Useful fields include:

- `mapping_strategy`
- `translated_subnets`
- `real_subnets`
- `host_mappings`
- `customer_sources`
- `interface`
- `output_mark`
- `tcp_mss_clamp`
- `route_via`
- `route_dev`

Important meaning:

- `selectors.local_subnets` is the customer-visible far-end selector
- `outside_nat.translated_subnets` should match that customer-visible selector
- `outside_nat.real_subnets` is the real local/core subnet behind the head end
- `selectors.remote_host_cidrs` scopes NAT and effective IPsec remote selectors
  to concrete customer hosts or smaller customer CIDRs when set
- `selectors.remote_subnets` remains the broader customer encryption domain

Detailed model:

- [HEADEND_OUTSIDE_NAT_AND_OVERLAP_MODEL.md](HEADEND_OUTSIDE_NAT_AND_OVERLAP_MODEL.md)

## Secret Handling

The customer source file should never hold inline PSKs.

Use:

```yaml
psk_secret_ref: /muxingrpdb/customers/<customer-name>/psk
```

The source file is allowed to reference the secret, but the secret value should
not live in Git.

## Target Minimal Authoring Shape

The target authoring experience is:

- normal site-to-site VPN inputs
- `customer_name`
- `customer_class`
- logical backend placement
- VPN compatibility and interoperability inputs
- interesting traffic intent
- post-IPsec NAT intent where needed

The platform should then allocate the transport/runtime namespaces
automatically.

That model is tracked in:

- [PROVISIONING_INPUT_MODEL.md](PROVISIONING_INPUT_MODEL.md)

## Validation Target

The machine-readable schema for this file lives at:

- [customer-source.schema.json](../config/schema/customer-source.schema.json)
