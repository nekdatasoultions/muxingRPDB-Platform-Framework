# Translation And Bridge Scale Decisions

## Purpose

This document closes the Phase 2 design gate for the repo-only RPDB scale plan.

It records the chosen implementation direction for the three remaining growth
areas that still sit behind the now-completed pass-through `nftables`
classification backend:

- muxer translation
- NFQUEUE bridge handling
- head-end post-IPsec NAT

The goal here is to preserve the design choices that removed guessing before
Phase 3 and Phase 4 implementation work started, and to keep those choices
anchored to measured numbers after Phase 3 landed.

## Inputs Used

The decisions below were originally anchored to the Phase 2 compatibility
baseline:

- `build/repo-verification/scale-baseline-summary-phase2-compat.json`
- `build/repo-verification/scale-baseline-summary-full-legacy-iptables.json`

Those decision-time numbers were:

- strict non-NAT at `20k`: `160000` remaining legacy muxer rules
- NAT-T at `20k`: `300000` remaining legacy muxer rules
- NAT-T netmap at `20k`: `80000` head-end post-IPsec NAT apply commands

The current repo-only Phase 3 implementation result is now:

- strict non-NAT at `20k`: `0` remaining legacy muxer rules
- NAT-T at `20k`: `0` remaining legacy muxer rules
- NAT-T netmap at `20k`: `80000` head-end post-IPsec NAT apply commands

That means muxer translation is no longer the remaining linear rule-growth
source in repo-only verification. The open scale gaps now sit in the bridge
path, head-end activation shape, shell fan-out, and explicit threshold gates.

## Decision Summary

The corrected chosen strategies are:

- muxer translation: move to batched `nftables` NAT maps
- NFQUEUE bridge: move to shared queue hooks plus a manifested bridge worker
- head-end post-IPsec NAT: move to batched `nftables` NAT artifacts

This is an `nftables`-first strategy.

Earlier planning allowed `iptables-restore` as the head-end default because it
would have reduced command fan-out while preserving current `NETMAP` and
explicit host-map semantics. That was only a transitional compatibility idea,
not the final RPDB scale direction.

The corrected rule is:

- `nftables` where the muxer benefits from shared maps and batch apply
- a worker-manifest model where userspace bridging is the real stateful object
- `nftables` for head-end post-IPsec NAT unless repo tests prove a required
  behavior cannot be represented safely
- `iptables` only as a documented fallback exception, never as the default
  scale path

## 1. Muxer Translation Decision

### Scope

This decision covers the muxer-side translation rules currently emitted in:

- `nat_prerouting_rules`
- `nat_postrouting_rules`

for:

- UDP/500
- UDP/4500
- ESP
- strict non-NAT reply preservation
- NAT-T backend delivery
- forced `4500 -> 500` bridge mode

### Current Problem

At Phase 2 decision time, after the classification layer moved to `nftables`,
the remaining muxer rule growth was still dominated by per-customer
translation rules.

At `20k` customers, the measured repo-only baseline still shows:

- `160000` muxer legacy rules for strict non-NAT
- `300000` muxer legacy rules for NAT-T

Those counts are largely translation, not classification.

### Chosen Strategy

Use a dedicated `nftables` NAT backend for pass-through translation.

The Phase 3 implementation uses:

- one shared nat table for pass-through translation
- batched map/set render for steady-state customer translation data
- one `nft -f` apply for the translation table per repo-modeled update

The model should use explicit objects for:

- UDP/500 DNAT targets
- UDP/4500 DNAT targets
- forced `4500 -> 500` DNAT targets
- ESP DNAT targets
- UDP/500 reply SNAT targets
- UDP/4500 reply SNAT targets
- ESP reply SNAT targets

### Why This Is The Right Choice

This layer still lives on the muxer, and its current pain is exactly what
`nftables` maps are good at:

- peer-specific destination rewrite
- shared rule hooks with data moved into maps
- single-batch replacement instead of thousands of shell calls

That gives us a real way to remove the remaining classification-adjacent linear
growth from the muxer dataplane without changing customer semantics.

### Behavior That Must Stay The Same

Phase 3 had to preserve, and repo-only verification now confirms:

- strict non-NAT customers still preserve shared public identity semantics
- true NAT-T customers still deliver encrypted traffic to the backend head-end
- forced `4500 -> 500` customers still rewrite inbound UDP/4500 to backend
  UDP/500
- reply traffic still uses the tracked head-end egress source identities
- customer-scoped remove only removes the selected customer from the rendered
  translation inventory

### Repo-Only Boundary

Current repo-only state:

- muxer translation is implemented through shared `nftables` NAT maps
- customer-scoped remove rebuilds the remaining translation inventory
- the verifier compares the current backend against both the Phase 2
  compatibility baseline and the full legacy baseline
- NFQUEUE bridge and head-end activation are still open scale gaps

## 2. NFQUEUE Bridge Decision

### Scope

This decision covers the userspace-assisted bridge flows that exist today for:

- forced `4500 -> 500` bridge customers
- NAT-D DPI rewrite customers

### Current Problem

The bridge path is not just a rule problem. It is a stateful userspace path.

Today the repo models it as per-customer `iptables` `NFQUEUE` rules and related
mark-restoration rules. That is not a good long-term representation of the real
runtime object we need to manage.

### Chosen Strategy

Model the bridge path as two things:

1. shared queue selector hooks in the dataplane
2. a manifested bridge worker state model

Phase 4 should therefore implement:

- shared queue hooks driven by `nftables` selector sets where possible
- a bridge manifest that lists the customers requiring:
  - `force4500_in`
  - `force4500_out`
  - `natd_dpi_in`
  - `natd_dpi_out`
- customer-scoped apply/remove as set or manifest rebuild, not permanent
  customer-specific queue rules spread across the dataplane

### Why This Is The Right Choice

The actual scarce object here is not just a rule slot. It is the userspace
bridge workload and its flow state.

Treating that workload as a manifested worker model gives us:

- a clean place to track which customers really require the bridge
- a measurable queue-group model in the scale harness
- a path away from one rule per customer just to reach the userspace worker

### Behavior That Must Stay The Same

Phase 4 implementation must preserve:

- forced `4500 -> 500` bridging still works in both directions
- NAT-D DPI rewrite customers still get the userspace-assisted path they need
- skb mark restoration still happens after userspace mutation when required
- customers without bridge requirements do not consume bridge state

### Repo-Only Boundary

Until Phase 4 is implemented and measured, the bridge layer remains an open
scale gap.

## 3. Head-End Post-IPsec NAT Decision

### Scope

This decision covers head-end post-IPsec NAT for:

- one-to-one netmap
- explicit host mapping
- route and mark carry-through already modeled in the bundle

### Current Problem

The repo baseline shows the head-end NAT layer still expands linearly in apply
commands.

At `20k` NAT-T netmap customers, the repo-only baseline records:

- `80000` head-end post-IPsec NAT apply commands

That is not acceptable as the long-term activation shape.

### Chosen Strategy

Move the head-end NAT semantic backend to generated `nftables` artifacts.

The next implementation phase should treat the head-end bundle as:

- one generated `nftables` apply batch for the customer NAT state
- one generated `nftables` remove batch for the customer NAT state
- structured state metadata for table, chain, set, and map names
- customer-owned state objects that keep unrelated customers untouched

### Why This Is The Right Choice

This layer relies on semantics like one-to-one netmap-style translation and
explicit host mapping.

The biggest current problem is not the semantic expression itself. The biggest
problem is line-by-line shell growth.

A batched `nftables` path gives us:

- a real path away from `iptables` on the scale-critical head-end NAT layer
- table, chain, set, and map objects that can be rendered and reviewed
- batch application through `nft -f`
- a cleaner route to customer-scoped apply/remove semantics

### Behavior That Must Stay The Same

Implementation must preserve:

- one-to-one netmap translation semantics
- explicit host-map translation semantics
- customer-scoped install, validate, and remove
- route and mark carry-through already modeled in the bundle

If any of those semantics cannot be represented in `nftables`, the work must
stop and write a problem statement before accepting an `iptables` fallback.

### Repo-Only Boundary

Until the bundled head-end activation changes to the `nftables` path, head-end
NAT is still a measured open scale gap.

## Implementation Order

The implementation order remains:

1. muxer translation
2. NFQUEUE bridge
3. head-end activation/backend cleanup as part of the same measured scale work

That order is deliberate because:

- muxer translation is the largest remaining muxer-side rule-growth source
- the bridge path depends on that translation boundary being clear
- head-end NAT batching can proceed after the muxer-side data model is stable

## Verification Contract For The Next Phases

Phase 3 and Phase 4 must add machine-checked evidence for:

- which backend is active for translation
- whether customer-scoped remove rebuilds only the remaining translation state
- how bridge queue selectors are counted
- how many head-end activation commands remain after batching

These decisions should be treated as the contract the next implementation
phases must satisfy.
