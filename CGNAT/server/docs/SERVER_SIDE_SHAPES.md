# Server-Side Shapes

## Purpose

This document breaks the CGNAT design into the pieces that are configured on
servers after the underlying infrastructure exists.

For this project, "server-side shapes" means host-level or service-level
configuration rendered onto the CGNAT HEAD END, CGNAT ISP HEAD END, and
connected backend tiers.

## What Counts as Server-Side Shapes

### Outer Tunnel Server-Side Shape

Server-side configuration for the outer tunnel includes:

- certificate-authenticated outer tunnel behavior
- outer tunnel interfaces used by the host
- service-side identity binding for the outer tunnel

### CGNAT HEAD END Server-Side Shape

Server-side configuration for the CGNAT HEAD END includes:

- inner VPN classification behavior
- GRE steering behavior
- host-side interface references used for GRE or tunnel processing
- validation expectations for the role

### Backend VPN Head-End Server-Side Shape

Server-side configuration for the backend service path includes:

- public loopback termination model
- inner VPN termination expectations
- translation mode and translation boundary behavior
- return-path expectations

### Customer Device / Service Shape

The customer service shape includes:

- known inside customer identity
- customer key references
- customer-original inside space
- platform-assigned inside space when translation is enabled

## What Is Not a Server-Side Shape

These are not primarily server-side shapes:

- EC2 instance creation
- subnet placement
- VPC selection
- EIP allocation

Those belong to the infra deployables layer.

## Current Server-Side Shape Sources

In the current model, server-side shapes are assembled from:

- `framework` behavior definitions
- `sot` service identity and addressing intent
- selected `operations` values such as interfaces, backend inventory, and
  loopback references

## Why This Split Matters

This split makes it easier to answer:

- what gets deployed as AWS infrastructure
- what gets rendered onto instances after they exist
- what comes from SoT versus what comes from operations

## Acceptance Criteria

This document is complete enough for the current phase when:

- server-side behavior is clearly separated from infra deployables
- outer tunnel, GRE steering, backend termination, and translation are all
  represented as server-side concerns
