# Address Translation

## Purpose

This document defines the address-translation model for the CGNAT design.

The core requirement is that the platform must be able to translate traffic
from customer-original inside space to platform-assigned inside space while
keeping return traffic correct and predictable.

## Translation Objective

The translation model must support these outcomes:

- preserve a clean separation between customer-owned addressing and
  platform-assigned addressing
- allow the backend VPN head end to present service-side traffic using the
  assigned space when required
- reverse the translation correctly for return traffic
- keep translation intent variable-driven and SoT-aware

## Translation Boundary

The current design assumes the primary translation boundary lives on the backend
VPN head end after inner VPN termination.

That means:

- the CGNAT HEAD END steers
- the backend VPN head end terminates
- the backend VPN head end performs translation when required

This keeps service-side routing and translation ownership in the same tier.

## Addressing Terms

### Customer-Original Inside Space

The customer's original inside addressing before any platform-side translation.

### Platform-Assigned Inside Space

The addressing the platform assigns and expects to use after translation where
required.

## Translation Modes

The framework should eventually support at least these conceptual modes:

### 1. No Translation

Customer traffic is preserved as-is after inner VPN termination.

Use when:

- overlap is not a concern
- platform-assigned space is not required for the service

### 2. One-to-One Translation

Customer-original addresses are mapped to corresponding platform-assigned
addresses.

Use when:

- a single host or small fixed set of identities must be preserved through a
  deterministic mapping
- the customer must be represented by platform-owned addresses on the
  service side

### 3. Subnet or Pool Translation

Customer-original space is translated into a platform-assigned subnet or pool.

Use when:

- a broader inside-address domain must be normalized into platform-owned space
- service routing expects a platform-assigned range

The first working version does not need to implement every mode, but the design
should leave room for them.

## Translation Flow

```text
Customer Device
  ->
inner S2S VPN
  ->
Backend VPN Head End
  ->
terminate inner VPN
  ->
translate customer-original inside space to platform-assigned inside space
  ->
route toward services
  ->
reverse translation on reply
  ->
return through backend VPN head end
```

## Reverse-Path Requirement

Reverse translation must happen on the same logical service boundary that owns
the forward translation.

The design must avoid:

- service-side replies bypassing the backend VPN head end
- asymmetric routing that skips reverse translation
- ambiguous mappings that make the reply path nondeterministic

## Ownership Model

### Framework-Owned

- translation role boundaries
- supported translation-mode definitions
- validation rules for mapping completeness

### Operations-Owned

- environment-specific rendering details
- any deployment values required to activate translation in a given AWS
  environment

### SoT-Owned

- customer-original inside space intent
- platform-assigned inside space intent
- mapping relationships when translation is required

## Validation Expectations

The framework should eventually validate that:

- translation intent is either explicitly enabled or explicitly absent
- customer-original and platform-assigned spaces are both known when
  translation is enabled
- mappings are non-overlapping where required
- the selected translation mode is compatible with the intended service shape

## Open Design Questions

- What is the minimum translation mode needed for the first working version?
- Which translation details belong in SoT versus operations inputs?
- How should translation intent be rendered in the first config contract?
- What validation signal best proves reverse-path correctness during testing?

## Acceptance Criteria

This document is complete enough for the current phase when:

- the translation boundary is explicit
- customer-original and platform-assigned space are clearly separated
- reverse-path expectations are explicit
- ownership across framework, operations, and SoT is clear
