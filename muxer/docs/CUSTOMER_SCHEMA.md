# Customer Schema

## Purpose

This document defines the concrete customer source shape for the RPDB model.

The customer source file is the authoring record. It is not the final rendered
customer module. It is the input that gets merged with shared defaults and
class defaults before it is written to DynamoDB and rendered into customer
artifacts.

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

### `customer.selectors`

Required:

- `local_subnets`
- `remote_subnets`

### `customer.backend`

Optional section.

Useful fields:

- `role`
- `underlay_ip`

If omitted, the class defaults should provide the backend role.

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
- `local_id`
- `remote_id`
- `ike`
- `esp`
- `dpddelay`
- `dpdtimeout`
- `dpdaction`
- `ikelifetime`
- `lifetime`
- `forceencaps`
- `mobike`
- `fragmentation`
- `mark`
- `vti_interface`
- `vti_routing`
- `vti_shared`
- `bidirectional_secret`

### `customer.post_ipsec_nat`

Optional for the customer source, but when present it must include:

- `enabled`

Useful fields include:

- `translated_subnets`
- `translated_source_ip`
- `real_subnets`
- `core_subnets`
- `interface`
- `output_mark`
- `tcp_mss_clamp`
- `route_via`
- `route_dev`

## Secret Handling

The customer source file should never hold inline PSKs.

Use:

```yaml
psk_secret_ref: /muxingrpdb/customers/<customer-name>/psk
```

The source file is allowed to reference the secret, but the secret value should
not live in Git.

## Validation Target

The machine-readable schema for this file lives at:

- [customer-source.schema.json](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/config/schema/customer-source.schema.json)
