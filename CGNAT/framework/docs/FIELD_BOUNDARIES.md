# Field Boundaries

## Purpose

This document classifies the current CGNAT contract fields by what they
actually represent operationally.

The goal is to make it obvious which fields are:

- infra deployable
- server-side renderable
- external dependency
- framework control
- SoT service intent

## Categories

### 1. Framework Control Fields

These define reusable framework behavior and validation rules.

Examples:

- `framework.version`
- `framework.topology.outer_tunnel.auth_method`
- `framework.topology.outer_tunnel.peer_ip_mode`
- `framework.topology.inner_vpn.auth_method`
- `framework.topology.inner_vpn.termination_model`
- `framework.topology.handoff.transport`
- `framework.topology.translation.default_mode`
- `framework.topology.translation.boundary`
- `framework.placement_constraints.*`

These are not direct AWS deployables and are not host-specific config by
themselves. They tell the framework how to behave and what to validate.

### 2. Infra Deployable Fields

These represent AWS-side deployment choices and resource placement.

Examples:

- `operations.environment_name`
- `operations.aws.region`
- `operations.aws.vpc_id`
- `operations.cgnat_head_end.instance_name`
- `operations.cgnat_head_end.instance_type`
- `operations.cgnat_head_end.subnet_id`
- `operations.cgnat_head_end.public_eip_allocation_id`
- `operations.cgnat_isp_head_end.instance_name`
- `operations.cgnat_isp_head_end.instance_type`
- `operations.cgnat_isp_head_end.transit_subnet_id`
- `operations.cgnat_isp_head_end.customer_subnet_id`
- `operations.gre_inventory.assignment_mode`

These are the fields that tell us what AWS-side resources need to exist and
where they should be placed.

### 3. Server-Side Renderable Fields

These represent host/service-side configuration that is rendered onto servers
after infrastructure exists.

Examples:

- `operations.cgnat_head_end.outer_tunnel_interface`
- `operations.cgnat_head_end.gre_source_interface`
- `operations.cgnat_isp_head_end.outer_tunnel_source_interface`
- `operations.cgnat_isp_head_end.customer_facing_interface`
- `sot.identities.outer_tunnel_identity_ref`
- `sot.identities.inner_customer_identity`
- `sot.identities.customer_loopback_ip`
- `sot.customer_devices[*].inner_vpn_auth_ref`
- `sot.customer_devices[*].known_inside_identity`
- `sot.addressing.translation_mode`
- `sot.addressing.customer_original_inside_space`
- `sot.addressing.platform_assigned_inside_space`
- `sot.backend_selection.preferred_class`
- `sot.backend_selection.customer_facing_public_ip`
- `sot.backend_selection.termination_public_loopback`

These fields help generate the server-side shapes for:

- outer tunnel behavior
- inner VPN behavior
- GRE steering
- translation

### 4. External Dependency Fields

These represent existing shared assets or references that the framework depends
on but does not itself claim to create in the current project block.

Examples:

- `operations.backend_vpn_head_ends`
- `operations.gre_inventory.inventory_ref`
- `operations.certificates.cgnat_head_end_server_cert_ref`
- `operations.certificates.cgnat_isp_head_end_client_cert_ref`

These are dependencies we must point at correctly before real deployment.

### 5. SoT Service-Intent Fields

These represent service identity and intent owned by the source of truth.

Examples:

- `sot.service_id`
- `sot.customer_id`
- `sot.identities.*`
- `sot.addressing.*`
- `sot.backend_selection.*`
- `sot.customer_devices[*].name`
- `sot.customer_devices[*].subnet_id`

These fields tell the framework what service is being expressed, not how AWS
resources are created.

## Important Notes

- Some fields are server-renderable and SoT-owned at the same time. That is
  not a contradiction. Ownership and deployment category are different axes.
- Some operations fields are infra deployable while others are server-side
  renderable. `instance_type` is infra; `outer_tunnel_interface` is
  server-side.
- The framework renderer should preserve this distinction in generated build
  artifacts.

## Acceptance Criteria

This document is complete enough for the current phase when:

- the field categories are explicit
- the difference between ownership and deployability is explicit
- the categories line up with the rendered build outputs
