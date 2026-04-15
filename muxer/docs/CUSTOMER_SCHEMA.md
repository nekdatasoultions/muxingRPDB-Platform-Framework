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

- [VPN_SERVICE_INTENT_MODEL.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/VPN_SERVICE_INTENT_MODEL.md)

The target operator-facing contract is described in:

- [PROVISIONING_INPUT_MODEL.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/PROVISIONING_INPUT_MODEL.md)

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

### `customer.ipsec`

Optional per-customer IPsec overrides:

- `auto`
- `ike_version` (target field, not fully modeled yet)
- `local_id`
- `remote_id`
- `ike`
- `esp`
- `dpddelay`
- `dpdtimeout`
- `dpdaction`
- `ikelifetime`
- `lifetime`
- `replay_protection` (target field, not fully modeled yet)
- `pfs` or required-group flexibility (target field, not fully modeled yet)
- `forceencaps`
- `mobike`
- `fragmentation`
- `clear_df_bit` (target field, not fully modeled yet)
- `mark`
- `vti_interface`
- `vti_routing`
- `vti_shared`
- `bidirectional_secret`

Current repo note:

- the compatibility schema already models the raw `ike` and `esp` strings plus
  DPD, force-encap, mobility, fragmentation, and VTI fields
- explicit `ike_version`, replay-protection control, DF-bit handling, and a
  richer multi-policy compatibility structure still need to be added

### `customer.post_ipsec_nat`

Optional for the customer source, but when present it must include:

- `enabled`

Useful fields include:

- `mapping_strategy` (target field, not fully modeled yet)
- `translated_subnets`
- `translated_source_ip`
- `real_subnets`
- `core_subnets`
- `host_mappings` (target field, not fully modeled yet)
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

- [PROVISIONING_INPUT_MODEL.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/PROVISIONING_INPUT_MODEL.md)

## Validation Target

The machine-readable schema for this file lives at:

- [customer-source.schema.json](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/config/schema/customer-source.schema.json)
