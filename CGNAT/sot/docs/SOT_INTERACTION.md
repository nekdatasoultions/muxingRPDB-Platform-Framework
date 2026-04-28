# SoT Interaction

## Purpose

This document defines how the CGNAT framework is expected to interact with the
source of truth.

The SoT is the canonical owner of service intent and identity relationships.
The framework should consume SoT-driven inputs rather than rely on hidden
manual decisions.

For the current project block, CGNAT should assume:

- the SoT database platform may be shared
- CGNAT record shapes are CGNAT-owned
- muxer-owned SoT schemas and item shapes are not assumed to change

## SoT Role

The SoT should provide the intent needed to answer:

- which customer/service is being deployed
- which outer-tunnel identity belongs to the CGNAT ISP HEAD END
- which inner customer identity belongs to the service
- which customer loopback identity belongs to the service
- which backend class or backend target is intended
- which customer-original and platform-assigned address spaces belong to the
  service

## Required SoT Inputs

At minimum, SoT inputs should provide:

- service_id
- customer_id
- outer_tunnel_identity_ref
- inner_customer_identity
- customer_loopback_ip
- customer_original_inside_space
- platform_assigned_inside_space when translation is enabled
- preferred backend class
- termination public loopback
- Customer Device identity and inside-address references

## SoT Responsibilities

The SoT owns:

- service identity
- customer identity references
- address assignment intent
- backend selection intent
- inventory relationships needed to connect service intent to deployment

The SoT contract for CGNAT should therefore be designed as a CGNAT-owned input
model even if the underlying database or storage platform is shared with other
systems.

The SoT does not own raw environment deployment values like instance type or
subnet placement. Those belong to operations.

## Framework Expectations

The framework should be able to:

- validate SoT input completeness
- combine SoT inputs with framework rules and operations inventory
- render deployment shapes without inventing missing service identity

## Operations Relationship

The SoT and operations layers must stay separate:

- SoT says what service is intended
- operations says where the environment can host it
- the framework binds the two into deployable shapes

The same separation applies to backend integration:

- SoT may express backend intent or backend class
- the framework translates that into a backend-facing contract
- the current backend is not changed as part of that step

## Go / No-Go Relevance

We are not ready for test deployment unless the SoT interaction contract is
clear enough to:

- identify the service unambiguously
- identify the backend class or target unambiguously
- identify translation intent unambiguously

## Acceptance Criteria

This document is complete enough for the current phase when:

- SoT-owned values are explicit
- the SoT/operations boundary is explicit
- the framework expectations for consuming SoT inputs are explicit
- the boundary between CGNAT-owned SoT shapes and muxer-owned shapes is explicit
