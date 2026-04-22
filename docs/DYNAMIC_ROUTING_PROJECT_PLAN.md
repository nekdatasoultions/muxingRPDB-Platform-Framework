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
- Customer 4 currently needs `outside_nat.route_via: 172.31.63.44` and
  `outside_nat.route_dev: ens36` because direct routing to
  `194.138.36.86/32` made the NAT head end ARP on `ens36` instead of sending
  traffic to the clear-side router.

## Customer 4 GRE/NAT-T Lessons

This plan was written before the customer-scoped GRE transport path was fixed.
The working live path now proves that GRE and IPsec can be correct while the
clear-side route is still wrong:

- Customer 4 NAT-T promotion installed a per-customer GRE transport between
  the muxer and NAT head end.
- The muxer forwarded UDP/4500 ESP-in-UDP from the customer into the NAT
  head-end path.
- The NAT head end installed the IPsec Child SAs and decrypted protected
  traffic.
- Traffic for `10.128.4.2/32` matched the outside-NAT translated selector.
- The translated real destination `194.138.36.86/32` failed when rendered as
  `ip route replace 194.138.36.86/32 dev ens36`.
- The failure mode was ARP, not GRE: the head end sent ARP requests for
  `194.138.36.86` on `ens36` and received no reply.
- Replacing that route with
  `ip route replace 194.138.36.86/32 via 172.31.63.44 dev ens36` restored
  successful customer-to-core ping.

Dynamic routing therefore has two independent responsibilities:

- derive the customer-scoped GRE return route for IPsec transport packets
- derive the clear-side route for outside-NAT real subnets after decryption

Validation must test both. A green GRE interface, loaded swanctl connection,
and nonzero Child SA counters are necessary but not sufficient; the generated
package must also prove that real protected destinations route through the
correct clear-side next hop and do not create direct ARP-only host routes.

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
- customer-scoped GRE transport defaults and overlay next-hop policy
- clear-side route ownership rules for translated outside-NAT real subnets
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
- GRE return interface and overlay next-hop derivation for the selected
  customer transport
- explicit policy for whether a real subnet is directly connected or must use
  a clear-side next hop
- validation probe source
- validation probe targets

Validation:

- environment examples validate
- missing route profile blocks customers that require outside NAT
- non-outside-NAT customers do not require outside NAT route profile fields
- a host route such as `194.138.36.86/32 dev ens36` is rejected when the
  profile says the subnet must route via `172.31.63.44`

### Step 2: Move route derivation into provisioning

Teach customer artifact rendering to derive outside NAT route commands from
the selected environment/head-end profile instead of relying on customer
request fields.

Validation:

- Customer 4 dry-run with NAT-T observation renders the NAT head-end route
  through the NAT head-end route profile
- Customer 4 dry-run renders
  `ip route replace 194.138.36.86/32 via 172.31.63.44 dev ens36`, not a direct
  `dev ens36` route
- Customer 4 dry-run without observation starts non-NAT and does not require a
  NAT route profile until promotion
- generated head-end route artifacts contain the selected route next hop
- generated head-end route artifacts still contain the customer-scoped GRE
  return route for the observed peer public IP
- generated customer request artifacts do not require `route_via` or
  `route_dev`

### Step 3: Add promotion-aware route generation

When NAT-T promotion moves a customer from non-NAT to NAT, the promoted package
must re-resolve routes against the NAT head-end profile.

Validation:

- initial non-NAT package is clean
- NAT-T observation produces a NAT package
- NAT package contains NAT head-end route commands
- NAT package reuses the GRE transport fixes: muxer table routes to the
  customer GRE interface, NAT head end returns transport traffic through the
  GRE overlay, and clear-side routes are derived separately
- stale non-NAT route assumptions do not carry into NAT package output

### Step 4: Add hard validation gates

Add repo verification checks so this cannot silently regress.

Validation:

- outside NAT customer without required selected head-end profile fails
  dry-run clearly
- outside NAT customer with selected profile passes dry-run
- generated route commands cannot install a direct clear-side route when the
  selected profile requires a next hop
- validation probes include route lookup checks for each outside-NAT real
  subnet and reject ARP-only failures where the next hop is missing
- validation probes include GRE/IPsec and clear-side route checks as separate
  results so a GRE fix cannot hide a post-decrypt routing failure
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
