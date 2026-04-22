# Dynamic-routing Project Plan

## Purpose

This project pins the next routing-model improvement for RPDB.

The current Customer 4 tactical safety fix can continue, but the final platform
model should not require customer request files to carry head-end-specific
route implementation details such as `route_via` or `route_dev`.

The target operating model remains:

```text
operator fills out one customer request
operator runs one provisioning script
RPDB selects the stack and platform routing details automatically
```

## Problem Statement

Outside NAT and return-path routing currently mix customer intent with platform
implementation details. A customer request can describe that real traffic such
as `194.138.36.86/32` should be represented to the customer as translated
traffic such as `10.128.4.2/32`, but the request should not need to know which
head-end interface or next-hop router makes that route work after final stack
selection. That information belongs to the RPDB environment and selected
head-end profile.

## Current Tactical State

- Customer request files can describe outside NAT intent.
- Customer request files can currently carry `outside_nat.route_via` and
  `outside_nat.route_dev`.
- This is acceptable as a temporary safety pin for active testing.
- This is not the final model.
- Dynamic NAT-T selection remains separate from outside NAT intent.
- Operators should still not select NAT-T or non-NAT in the customer request.

## Target State

Customer request files should contain service intent only:

- customer name
- peer identity and peer public IP
- local and remote encryption domains
- remote host CIDRs when overlapping remote encryption domains need scoping
- outside NAT real and translated subnets
- post-IPsec NAT real, translated, and core subnets
- IPsec interoperability settings

Platform/environment profiles should contain placement and routing facts:

- muxer target
- NAT head-end targets
- non-NAT head-end targets
- per-head-end inside/core interfaces
- per-head-end route next-hop defaults
- outside NAT next-hop policy
- return-path route policy
- validation probes for selected head-end reachability

Provisioning should derive final routing this way:

```text
customer request
  -> default non-NAT package
  -> optional NAT-T observation
  -> final head-end family
  -> selected environment head-end profile
  -> generated routes and nftables artifacts
```

## Proposed Implementation Steps

### Step 1: Model head-end routing profiles

Add environment schema fields for head-end route profiles.

The profile should support:

- head-end family: `nat` or `non_nat`
- interface used for outside NAT real-subnet reachability
- next-hop used for outside NAT real-subnet reachability
- optional route table or policy name
- validation probe source
- validation probe targets

Validation:

- environment examples validate
- missing route profile blocks customers that require outside NAT
- non-outside-NAT customers do not require outside NAT route profile fields

### Step 2: Move route derivation into provisioning

Teach customer artifact rendering to derive outside NAT route commands from
the selected environment/head-end profile instead of relying on customer
request fields.

Validation:

- Customer 4 dry-run with NAT-T observation renders the NAT head-end route
  through the NAT head-end route profile
- Customer 4 dry-run without observation starts non-NAT and does not require a
  NAT route profile until promotion
- generated head-end route artifacts contain the selected route next hop
- generated customer request artifacts do not require `route_via` or
  `route_dev`

### Step 3: Add promotion-aware route generation

When NAT-T promotion moves a customer from non-NAT to NAT, the promoted package
must re-resolve routes against the NAT head-end profile.

Validation:

- initial non-NAT package is clean
- NAT-T observation produces a NAT package
- NAT package contains NAT head-end route commands
- stale non-NAT route assumptions do not carry into NAT package output

### Step 4: Add hard validation gates

Add repo verification checks so this cannot silently regress.

Validation:

- outside NAT customer without required selected head-end profile fails
  dry-run clearly
- outside NAT customer with selected profile passes dry-run
- generated artifacts remain `nftables` only
- no `iptables` or `iptables-restore` fallback is introduced

### Step 5: Update operator docs

Update onboarding docs to say that outside NAT route placement is platform
owned.

Validation:

- customer examples do not teach operators to pick head-end next hops
- docs explain that operators provide NAT intent, not implementation routing
- one-command provisioning remains the primary operator workflow

## Acceptance Criteria

- Customer request files no longer need `outside_nat.route_via`.
- Customer request files no longer need `outside_nat.route_dev`.
- RPDB derives those values from the selected environment/head-end profile.
- NAT-T promotion re-renders routes using the NAT head-end profile.
- Dry-run blocks unsafe or incomplete route profiles before live apply.
- Repo verification proves generated artifacts stay `nftables` only.
- The one-script customer deployment workflow remains intact.

## Guardrails

- Do not modify MUXER3.
- Do not use `iptables`.
- Do not use `iptables-restore`.
- Do not touch live nodes as part of this project plan.
- Do not make the operator choose NAT-T or non-NAT.
- Do not make the operator choose head-end route next hops.

## Current Decision

Do not change the active Customer 4 flow right now. Keep the tactical
`route_via` and `route_dev` request fields in place for the current test path.

This project is pinned so the next engineering pass can move those details into
the platform-owned dynamic routing model without disrupting the current
re-provision test.
