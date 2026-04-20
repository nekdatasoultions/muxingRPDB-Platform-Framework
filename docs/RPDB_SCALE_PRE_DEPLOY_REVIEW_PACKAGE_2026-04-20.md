# RPDB Scale Pre-Deploy Review Package 2026-04-20

## Purpose

This package is the repo-only review checkpoint after the head-end post-IPsec
NAT activation redesign.

It answers:

- what changed
- what was proven
- what still requires live validation
- whether deployment should proceed now

## Scope

This package is repo-only.

It includes:

- code changes
- staged customer artifact validation
- synthetic scale evidence
- two full repo verification runs

It excludes:

- AWS changes
- node rollout
- customer apply
- `MUXER3` changes

## What Changed

The repo now renders head-end post-IPsec NAT through customer-scoped nftables
artifacts:

- `nftables.apply.nft`
- `nftables.remove.nft`
- `nftables-state.json`
- `activation-manifest.json`

The staged head-end apply/remove helpers now install and validate those
artifacts instead of building post-IPsec NAT apply scripts from a head-end
iptables snippet.

The scale harness now counts the nftables batch activation units as the active
backend and preserves the old linear command shape only as comparison evidence.

## What Was Proven Repo-Only

The repo-only evidence proves:

- netmap NAT customer bundles render nftables DNAT/SNAT maps
- explicit host-map NAT customer bundles render nftables DNAT/SNAT maps
- staged head-end install validates the nftables artifacts
- staged head-end remove removes only the selected staged customer state
- `nat_t_netmap` passes at 1k, 5k, 10k, and 20k customers
- the full explicit scale report passes across all measured profiles
- full repo verification passed twice

## Scale Result

Current explicit result:

- overall report status: `passed`
- missing targets: none
- failing checks: none

For the previously failing `nat_t_netmap` profile:

- `20000` customer apply commands: `40000`
- `20000` customer rollback commands: `20000`
- max apply commands per customer: `2`

The preserved legacy comparison is:

- legacy `20000` customer apply commands: `80000`
- legacy `20000` customer rollback commands: `60000`
- legacy max apply commands per customer: `4`

## Deployment Recommendation

Current recommendation: `repo-only gate passed, live deployment still gated`

Why:

- the repo-only scale blocker is resolved
- the code and docs now enforce nftables-only head-end NAT activation for the
  accepted RPDB scale path
- live-node behavior has not been exercised in this execution block
- customer deployment still requires separate approval and live validation

## Required Next Gate

Before any customer apply, perform a live-node validation plan that verifies:

- nftables availability and version on the new RPDB muxer and VPN head ends
- staged artifact placement on the target nodes
- `nft -c -f` syntax validation on the target OS
- `nft -f` apply behavior on non-customer test artifacts
- rollback batch behavior
- tunnel traffic in both directions
- observability and rollback timing

## Stop Point

Do not:

- deploy code
- touch AWS
- touch nodes
- apply a customer
- modify `MUXER3`

This package is ready for review, not live execution.
