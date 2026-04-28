# CGNAT Workspace

## Purpose

This directory is the isolated working area for CGNAT architecture, planning,
prototype code, scripts, tests, and validation artifacts.

The CGNAT effort is a net-new ingress framework that hands traffic to the
current backend platform, but all active CGNAT work stays inside this directory
until a first working version exists and explicit approval is given for any
broader integration.

This work is intended to produce:

- a reusable CGNAT framework that can be deployed in different AWS
  environments
- an operations model that defines where and how that framework is actually
  deployed
- a SoT interaction model that defines how intent, inventory, identity, and
  deployment inputs are exchanged with the source of truth

## Scope

The target design is a two-layer model:

1. A carrier-side outer tunnel is established from the CGNAT ISP HEAD END to
   the CGNAT HEAD END.
2. The outer tunnel is authenticated with certificates and must not depend on a
   fixed public source IP.
3. Customer devices behind the CGNAT ISP HEAD END then send an inner S2S VPN
   through that outer tunnel.
4. The CGNAT HEAD END steers that inner VPN traffic across GRE to the selected
   backend NAT-T or non-NAT VPN head ends.
5. Backend VPN head ends terminate the inner VPN and may NAT customer-original
   inside space to platform-assigned inside space.

This means the project is not only about packet flow. It is also about:

- framework portability across AWS environments
- environment-specific operational deployment data
- first-class interaction with the SoT

## Guardrails

- All active CGNAT work stays under `CGNAT/`.
- No files outside `CGNAT/` are edited without explicit approval.
- No MUXER3 code is imported or reused as an implementation base.
- No muxer code or schema is changed as part of the current plan.
- No CGNAT work is pushed to GitHub or CodeCommit until a first working
  version exists and is reviewed.
- If work appears to require touching shared RPDB paths, stop and get approval
  first.

## Workspace Lanes

- [Framework](./framework/README.md)
- [AWS](./aws/README.md)
- [Server](./server/README.md)
- [SoT](./sot/README.md)

Useful script entry points:

- [AWS package builder](./aws/scripts/README.md)
- [Server package builder](./server/scripts/README.md)

Useful cross-lane references:

- [Backend Contract Map](./framework/docs/SHARED_INTEGRATION_MAP.md)

Rendered examples in `build/` now mirror the same split:

- `framework/`
- `aws/`
- `server/`
- `sot/`

## Working Layout

```text
CGNAT/
  README.md
  framework/
    docs/
    config/
    scripts/
    src/
  aws/
    docs/
    config/
    scripts/
  server/
    docs/
    config/
    scripts/
  sot/
    docs/
    config/
  tests/
  build/
```
