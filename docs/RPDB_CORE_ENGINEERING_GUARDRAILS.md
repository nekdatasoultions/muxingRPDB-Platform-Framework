# RPDB Core Engineering Guardrails

## Purpose

This is the standing guardrail contract for RPDB engineering work. It exists so
the project does not drift back into paths that were already rejected.

## Non-Viable Paths

These paths are not allowed as implementation, runtime, deployment, or fallback
paths for the RPDB scale design:

- `iptables`
- `iptables-restore`
- `MUXER3`
- legacy head-end `iptables` activation

`iptables` is not a viable RPDB runtime or generated-artifact backend. RPDB
runtime code and generated customer artifacts must use `nftables` for packet
classification, translation, bridge handling, and head-end post-IPsec NAT.

`iptables-restore` is not a viable fallback. It must not be used to make the
head-end post-IPsec NAT scale gate look green.

`MUXER3` is not a viable implementation fallback. It must not be modified, used
as the runtime source, or used as the deployment source for RPDB.

Plain guardrail: iptables-restore is not a viable fallback.
Plain guardrail: no RPDB runtime or generated customer artifact may depend on
iptables.
Plain guardrail: MUXER3 is not a viable implementation fallback.

## Required Direction

The accepted head-end post-IPsec NAT direction is:

- Linux `nftables`
- generated `nft -f` batch artifacts
- `nftables` tables, chains, sets, and maps
- repo-only staged verification before any live action

If a required behavior cannot be represented safely in `nftables`, stop and
write a problem statement plus a new design decision. Do not silently add an
`iptables` or `iptables-restore` fallback.

## Verification Guardrails

- Runtime package source/config must not contain `iptables`, `iptables-restore`,
  or `legacy_iptables` implementation paths.
- Generated customer bundles and staged/live-apply artifacts must not contain
  `iptables`, `iptables-restore`, `iptables-snippet`, or `legacy_iptables`.
- Scale and repo verification must prove the nftables backend is active for
  muxer classification, muxer translation, bridge handling, and head-end
  post-IPsec NAT.

## Operational Guardrails

- Stay inside this repository unless the user explicitly approves otherwise.
- Do not modify `MUXER3`.
- Do not touch AWS without explicit approval.
- Do not touch live nodes without explicit approval.
- Do not apply a customer without explicit approval.
- Do not move EIPs without explicit approval.
- Do not claim a gate passed unless the repo has repeatable verification for it.
- If a gate fails, write the problem statement, fix or redesign, and only then
  move forward.
