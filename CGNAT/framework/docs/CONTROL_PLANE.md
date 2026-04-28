# Control Plane

## Purpose

This document defines the control-plane model for the CGNAT project.

For this project, the control plane is not only about selecting backend VPN
head ends. It is also about separating:

- the reusable framework behavior
- the environment-specific operations layer
- the SoT inputs that drive both

## Design Principle

The CGNAT design must behave like a framework that can be deployed in multiple
AWS environments, not like a single hardwired build for one environment.

That means the control plane must clearly answer three different questions:

1. What is the reusable CGNAT framework expected to do?
2. What operational values are specific to a particular AWS deployment?
3. What values must come from the SoT?

## Three-Layer Control Model

### 1. Framework Layer

The framework layer owns the reusable behavior.

It should define:

- outer tunnel role separation
- inner VPN steering logic
- backend head-end selection behavior
- NAT ownership boundaries
- validation behavior
- expected configuration shapes

The framework layer should not own one-off environment facts such as a single
AWS account, one fixed subnet layout, or hardcoded public IP assumptions.

### 2. Operations Layer

The operations layer owns real deployment context.

It should define environment-specific values such as:

- AWS account and region
- VPC selection
- subnet assignments
- instance roles and placement
- EIP/public addressing
- security groups and related deployment-time controls
- certificate material references
- backend reachability choices
- rollout and rollback procedures

This is the layer that answers "where are we deploying this" and "how are we
operating it in this AWS environment."

### 3. SoT Layer

The SoT layer owns canonical intent and inventory inputs.

It should provide or define:

- customer/service identity
- outer-tunnel identity references
- address-assignment intent
- backend VPN head-end inventory
- environment inventory required by deployment logic
- mappings between customers, CGNAT roles, and backend service choices

The SoT layer should be the source of truth for structured intent, not a
side-channel afterthought.

## Control-Plane Responsibilities

### Outer Tunnel Control

The control plane must support:

- identifying the CGNAT ISP HEAD END through certificate-based outer identity
- accepting unknown, changing, or CGNATed source public identity
- associating outer-tunnel sessions with the correct service context

### Inner VPN Control

The control plane must support:

- identifying Customer Devices for inner VPN service
- carrying keys and customer identity material
- selecting the correct backend VPN head end or backend head-end class

### Translation Control

The control plane must support:

- customer-original inside space
- platform-assigned inside space
- ownership of translation intent
- validation that translation mappings are complete and non-ambiguous

### Placement Control

The control plane must support:

- subnet constraints for each role
- variable-driven EC2 placement and addressing
- validation that deployment inputs satisfy the approved placement model

## SoT Interaction Model

The framework should eventually consume a structured SoT contract rather than
depend on ad hoc operator edits.

At minimum, the SoT interaction model should account for:

- CGNAT service identity
- customer identity references
- outer-tunnel certificate identity references
- customer-original and platform-assigned address intent
- backend VPN head-end inventory and selection inputs
- deployment environment inventory used by operations

## Framework vs Operations vs SoT Ownership

The project should keep ownership boundaries explicit.

### Framework-Owned

- behavior
- validation logic
- config shapes
- role definitions
- steering logic expectations

### Operations-Owned

- concrete AWS environment values
- deployment target choices
- live rollout sequencing
- environment-specific certificate and addressing references

### SoT-Owned

- customer/service intent
- inventory relationships
- identity references
- assignment intent and mappings

## Go / No-Go Relevance

We are not ready for infrastructure testing until the control plane is clear
enough to answer:

1. which values come from the framework
2. which values come from operations
3. which values come from SoT
4. whether a test deployment can be rendered without hidden manual knowledge

## Acceptance Criteria for This Document

This document is complete enough for the current phase when:

- the framework/operations/SoT split is explicit
- outer identity and inner identity are clearly separated
- SoT is treated as a first-class input source
- the document supports the infrastructure test deployment Go / No-Go gate
