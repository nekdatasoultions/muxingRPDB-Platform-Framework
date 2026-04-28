# Backend Contract Fields

## Purpose

This document defines the concrete field shape for the backend-facing contract
used by CGNAT.

The goal is to make the handoff explicit without changing muxer-owned code.

## Contract Intent

The backend contract must preserve two truths at the same time:

1. the customer keeps targeting the same public IP already used by the current
   muxer-backed service
2. the packet path changes so traffic traverses:
   - `CGNAT ISP HEAD END`
   - outer tunnel
   - `CGNAT HEAD END`
   - GRE
   - selected backend head end

## Field Shape

### `record_type`

- value: `cgnat_backend_contract`
- purpose: identifies the rendered object type

### `service_id`

- owner: SoT
- purpose: ties the contract to one CGNAT service instance

### `customer_id`

- owner: SoT
- purpose: ties the contract to one customer identity

### `customer_facing_target`

Required fields:

- `target_public_ip`
- `description`

Purpose:

- records the public IP the customer still points to for the inner S2S VPN
- for the current Scenario 1 model, this must be the same existing public IP
  already used by the backend VPN head-end service

### `cgnat_path.outer_tunnel`

Required fields:

- `auth_method`
- `peer_ip_mode`
- `cgnat_isp_head_end_identity_ref`

Purpose:

- captures the ingress-side access contract that gets traffic into the CGNAT
  framework

### `cgnat_path.inner_vpn`

Required fields:

- `auth_method`
- `inner_customer_identity`

Purpose:

- captures the customer-service VPN identity and auth assumptions

### `gre_handoff`

Required fields:

- `transport`
- `inventory_ref`
- `assignment_mode`
- `cgnat_head_end_source_interface`
- `selected_backend_name`
- `selected_backend_gre_remote`

Purpose:

- defines how the CGNAT HEAD END reaches the chosen backend head end

### `backend_termination`

Required fields:

- `preferred_class`
- `termination_public_loopback`
- `selected_backend_public_loopback`

Purpose:

- captures the backend termination target and the current public loopback/public
  identity behavior
- for the current Scenario 1 model, the termination loopback must match the
  customer-facing target public IP

### `translation`

Required fields:

- `mode`
- `boundary`
- `customer_original_inside_space`
- `platform_assigned_inside_space`

Purpose:

- captures whether translation is expected and where the design places that
  boundary

### `path_statement`

Required fields:

- `summary`

Purpose:

- records the architecture rule in plain language so operators and reviewers do
  not confuse target identity with transport path

## Example Meaning

If the backend contract says:

- `customer_facing_target.target_public_ip = 198.51.100.10`
- `gre_handoff.inventory_ref = existing-shared-gre-space`
- `gre_handoff.assignment_mode = next_available`
- `gre_handoff.selected_backend_gre_remote = 172.31.40.222`
- `backend_termination.termination_public_loopback = 198.51.100.10`

then the intended behavior is:

- the customer still targets `198.51.100.10`
- the CGNAT HEAD END allocates its GRE endpoint from the existing shared GRE
  space using the next available assignment rule
- CGNAT carries that flow through the CGNAT ingress path
- the CGNAT HEAD END forwards the inner VPN over GRE to `172.31.40.222`
- the backend preserves the public-facing termination identity
- the customer-facing target and the backend termination loopback are the same
  existing backend VPN service IP

## Acceptance Criteria

This document is complete enough for the current phase when:

- the customer-facing public IP is explicit
- the GRE inventory source and allocation rule are explicit
- the GRE handoff target is explicit
- the backend loopback target is explicit
- the difference between identity and path is explicit
