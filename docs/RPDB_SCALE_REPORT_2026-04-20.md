# RPDB Scale Report 2026-04-20

## Scope

This report captures the repo-only RPDB scale result after the head-end
post-IPsec NAT activation redesign.

It covers:

- code and docs inside this repository only
- no AWS access
- no node access
- no customer deployment
- no `MUXER3` changes

## Evidence Sources

- `build/rpdb-headend-nat-nftables/full-scale-summary.json`
- `build/rpdb-headend-nat-nftables/full-scale-report.json`
- `build/rpdb-headend-nat-nftables/full-scale-report.md`
- `build/repo-verification/repo-verification-summary.json`
- `muxer/config/scale-thresholds.json`
- `muxer/config/scale-decisions.yaml`

## Summary

The explicit repo-only scale gate is now green for the measured target profiles.

Current result:

- overall explicit scale report status: `passed`
- missing target profiles: none
- failing checks: none
- full repo verification passed twice after the code change
- work remains stopped before live deployment

The previously failing profile, `nat_t_netmap`, now passes at `1000`, `5000`,
`10000`, and `20000` customers.

## Head-End NAT Change

The head-end post-IPsec NAT activation path no longer uses a head-end
`iptables` snippet as the active repo-modeled activation backend.

Customer bundles now carry:

- `headend/post-ipsec-nat/nftables.apply.nft`
- `headend/post-ipsec-nat/nftables.remove.nft`
- `headend/post-ipsec-nat/nftables-state.json`
- `headend/post-ipsec-nat/activation-manifest.json`

The staged head-end apply path writes those artifacts and generates a
customer-scoped apply script that runs:

- `nft -c -f`
- `nft -f`

The staged remove path uses the generated `nftables.remove.nft` batch.

## Measured `nat_t_netmap` Result

Before this fix, the `nat_t_netmap` profile measured:

- `20000` customers: `80000` apply commands
- `20000` customers: `60000` rollback commands
- max apply commands per customer: `4`

After this fix, the repo-only scale harness measures:

- `1000` customers: `2000` apply commands, `1000` rollback commands, max apply
  per customer `2`
- `5000` customers: `10000` apply commands, `5000` rollback commands, max
  apply per customer `2`
- `10000` customers: `20000` apply commands, `10000` rollback commands, max
  apply per customer `2`
- `20000` customers: `40000` apply commands, `20000` rollback commands, max
  apply per customer `2`

That satisfies the current explicit threshold model.

## What Passed

The full explicit scale report passed for:

- `strict_non_nat`
- `nat_t`
- `nat_t_netmap`
- `mixed`
- `force4500_bridge`
- `natd_bridge`

Each profile passed at:

- `1000`
- `5000`
- `10000`
- `20000`

## Honest Deployment Readiness Statement

The current repo-only scale result is:

- green for the measured repo-only target profiles
- backed by two successful full repo verification runs
- still not a live deployment approval

Live validation is still required for:

- node-local nftables behavior on real RPDB nodes
- operational latency on real hardware
- observability and rollback timing
- customer-path validation in both directions

## Stop Point

This report does not authorize:

- AWS actions
- node rollout
- customer apply
- `MUXER3` changes

The repo-only scale blocker for head-end post-IPsec NAT activation is resolved,
but the next gate is a separate live-node validation and deployment review.
