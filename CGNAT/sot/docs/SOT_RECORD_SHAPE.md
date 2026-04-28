# SoT Record Shape

## Purpose

This document defines the CGNAT-owned source-of-truth record shape for a single
service.

The intent is to keep CGNAT on the same storage platform if needed while still
owning its own record contract.

## Record Type

The first CGNAT SoT service record shape is:

- `record_type = cgnat_service`
- `version = 1`

## Top-Level Fields

### `service_id`

- owner: SoT
- purpose: unique CGNAT service identifier

### `customer_id`

- owner: SoT
- purpose: customer identity binding for the service

### `identities`

Required fields:

- `outer_tunnel_identity_ref`
- `inner_customer_identity`
- `customer_loopback_ip`

Purpose:

- captures the outer-tunnel identity reference and the inner customer-service
  identity separately
- captures the customer loopback identity used by Scenario 1 and similar
  service patterns

### `addressing`

Required fields:

- `customer_original_inside_space`
- `platform_assigned_inside_space`
- `translation_mode`

Purpose:

- records original customer space, assigned platform space, and translation
  intent

### `backend_selection`

Required fields:

- `preferred_class`
- `customer_facing_public_ip`
- `termination_public_loopback`

Purpose:

- records what backend class should be used
- records the public IP the customer keeps targeting
- records the backend loopback/public identity expected at termination
- for the current Scenario 1 model, these two public-IP values should match

### `customer_devices`

Required fields per device:

- `name`
- `subnet_id`
- `known_inside_identity`
- `inner_vpn_auth_ref`

Purpose:

- records the customer-side initiators that sit behind the CGNAT ISP HEAD END

## Ownership Notes

This record shape is:

- CGNAT-owned
- SoT-owned from a service-intent perspective
- independent of muxer-owned schemas

It may live in the same database platform, but it should not assume the same
item structure as the current backend platform.

## Example Meaning

If the record says:

- `customer_loopback_ip = 10.250.1.10`
- `customer_facing_public_ip = 198.51.100.10`
- `termination_public_loopback = 198.51.100.10`
- `preferred_class = nat_t`

then the meaning is:

- the customer loopback/service identity is `10.250.1.10`
- the customer still points the inner VPN at `198.51.100.10`
- the framework should select the NAT-T backend class
- the backend should preserve the current public-facing termination identity
- the same existing backend VPN service IP is being used as both the
  customer-facing target and the backend termination loopback

## Scenario 1 Loopback Rule

For the Scenario 1 demo:

- `customer_loopback_ip` should use non-overlapping `10.x` space

For production:

- `customer_loopback_ip` remains variable-driven
- the address does not have to stay in `10.x`
- non-overlap validation still applies

## Acceptance Criteria

This document is complete enough for the current phase when:

- the service identity fields are explicit
- the customer-facing public IP is explicit
- the backend selection fields are explicit
- the device-level customer inputs are explicit
