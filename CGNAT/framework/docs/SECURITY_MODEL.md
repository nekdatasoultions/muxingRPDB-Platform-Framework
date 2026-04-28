# Security Model

## Purpose

This document records the initial security model for the CGNAT framework.

The goal is to make trust boundaries and identity rules explicit before we move
toward deployable infrastructure shapes.

## Trust Boundaries

### Boundary 1: Public to Outer Tunnel

Traffic arriving from the public side is not trusted just because it can reach
the CGNAT HEAD END.

Trust begins only after:

- outer tunnel establishment
- successful certificate authentication

### Boundary 2: Outer Tunnel to Inner VPN

The outer tunnel grants transport into the platform. It does not grant service
identity for the inner VPN.

The inner VPN must remain separately identified and terminated on the backend
VPN head-end tier.

### Boundary 3: Inner VPN to Service Space

If translation is required, the backend VPN head end owns that translation
boundary and the reverse path associated with it.

## Identity Requirements

- outer tunnel identity must be certificate-authenticated
- inner VPN identity must remain key-based and customer-specific
- outer and inner identity must never be collapsed into a single trust claim

## Configuration and Secrets

Framework artifacts must separate:

- reusable design values
- environment-specific operational values
- secret references

Secret material should be referenced, not embedded, in deployable contract
examples wherever possible.

## Operational Security Expectations

- placement constraints must be validated before deployment
- backend inventory must be explicit
- return-path expectations must be explicit
- translation intent must be explicit when enabled

## Security Concerns to Carry Forward

- certificate storage and rotation model
- customer key storage and rotation model
- role-based access to deployment inputs
- auditability of SoT-driven changes
- backend selection integrity

## Acceptance Criteria

This document is complete enough for the current phase when:

- trust boundaries are explicit
- outer versus inner identity handling is explicit
- secret/reference separation is explicit
- the document supports the Go / No-Go review
