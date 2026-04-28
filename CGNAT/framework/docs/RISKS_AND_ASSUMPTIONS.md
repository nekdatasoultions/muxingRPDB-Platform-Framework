# Risks and Assumptions

## Purpose

This document records the key assumptions and risks for the CGNAT framework as
we move from architecture planning toward deployable shapes.

## Assumptions

- one CGNAT HEAD END is sufficient for the first working version
- one CGNAT ISP HEAD END is sufficient for the first working version
- backend NAT-T and non-NAT VPN head ends remain the service termination tier
- GRE remains the expected handoff mechanism unless later design work proves
  otherwise
- Scenario 1 demo PKI uses a local CA on the CGNAT HEAD END
- the first working version can validate deployment shapes without changing
  files outside `CGNAT/`

## Framework Risks

- the framework/operations/SoT boundary could drift if ownership stays implicit
- deployable shapes could become too environment-specific too early
- backend selection rules could remain too abstract to validate well

## Dataplane Risks

- return-path symmetry may be harder to prove than forward steering
- translation ownership could become ambiguous if not kept on the backend tier
- GRE endpoint assumptions could leak into framework logic if not kept
  variable-driven

## Operations Risks

- operational deployment data could get mixed into framework defaults
- subnet placement rules could be bypassed by manual edits if not validated
- test deployment scope could grow before the Go / No-Go gate is truly ready
- demo PKI choices could accidentally bleed into production assumptions if they
  are not labeled clearly

## SoT Risks

- SoT inputs may be underspecified for backend selection
- address assignment intent may not be detailed enough for translation
- inventory references may not line up cleanly with operations deployment data

## Control Risks

- touching files outside `CGNAT/` too early would break the agreed guardrail
- publishing to GitHub or CodeCommit too early would break the publication
  freeze
- moving to infrastructure deployment before the Go / No-Go gate would break
  the project sequence

## Acceptance Criteria

This document is complete enough for the current phase when:

- the main framework, dataplane, operations, and SoT risks are visible
- the most important working assumptions are written down
- the document supports the deployment readiness discussion
