# Identity Model

## Purpose

This document defines the identity model for the CGNAT design after removing
DDNS as a core architectural requirement.

The goal is to keep identity handling simple and explicit:

- the outer tunnel is identified by certificate-authenticated CGNAT ISP HEAD
  END identity
- the inner VPN is identified by customer-specific keying and known inside
  identity
- the architecture must tolerate changing public source IP without requiring
  DDNS to be a first-class dependency

## Identity Layers

### Outer Identity

The outer identity belongs to the CGNAT ISP HEAD END.

Required characteristics:

- certificate-authenticated
- not dependent on a fixed public peer IP
- stable from an identity perspective even if the source public IP changes

The outer identity is used to establish trusted transport into the CGNAT HEAD
END.

### Inner Identity

The inner identity belongs to the Customer Devices and their service context.

Required characteristics:

- uses customer-specific keys
- uses known inside customer identity
- remains separate from the outer certificate identity

The inner identity is used to steer and terminate the customer VPN correctly on
backend VPN head ends.

## Identity Ownership

### Framework-Owned

- role separation between outer and inner identity
- validation expectations for identity inputs
- rules for how identity is consumed during steering and termination

### Operations-Owned

- environment-specific certificate references
- deployment-time binding of roles to infrastructure

### SoT-Owned

- customer/service identity inputs
- outer-tunnel identity references
- mappings between customer service context and backend delivery intent

## Design Rules

- Outer and inner identity must remain separate.
- Certificate authentication is mandatory for the outer tunnel.
- The inner VPN must not depend on certificates.
- Changing source public IP must be tolerated by the outer access model.
- DDNS is not a core requirement of the current architecture.

## Acceptance Criteria

This document is complete enough for the current phase when:

- the outer and inner identity models are clearly separated
- the outer certificate-authenticated identity is explicit
- the inner customer identity model is explicit
- the design no longer depends on DDNS as a first-class architectural feature
