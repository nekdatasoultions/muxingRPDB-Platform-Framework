# CGNAT Live Status 2026-05-05

## Summary

Both live CGNAT scenarios are up:

1. **Scenario 1 / Customer 1**
   - outer tunnel: direct customer outer to the CGNAT head end
   - inner tunnel: active
   - **inside NAT**: `10.20.30.10 -> 10.20.20.10`
   - **outside NAT**: customer-visible `10.20.40.10 -> real 194.138.36.86`
   - validated with live ping:
     - `10.20.30.10 -> 10.20.40.10`

2. **Scenario 2 / Customer 2**
   - outer tunnel: shared ISP outer via **gateway 2**
   - customer device: inner-only
   - validated with live ping:
     - `10.20.30.11 -> 194.138.36.86`

## Live Infrastructure State

### CGNAT head end

- existing live head end remains in use
- supports both Scenario 1 and Scenario 2 simultaneously

### ISP gateway 2

- live instance exists and is in service
- public IP: `100.30.83.15`
- private IP: `172.31.57.183`
- forwarding enabled
- nftables baseline enabled
- **libreswan was not used**
- strongSwan runtime was staged deliberately

## Important Live Findings

### 1. Scenario 2 shared-ISP transport model

For the shared-ISP topology, the working live model is:

- **identity** remains customer loopback identity:
  - `10.250.1.11`
- **transport source** on the wire uses the customer underlay address:
  - `172.31.48.21`

This was required to make the shared-ISP topology work reliably across the AWS
VPC path to gateway 2.

This behavior is proven live and should be folded back into the framework as the
expected transport behavior for `shared_isp_gateway`.

### 2. Customer 1 NAT return path

Customer 1 live NAT required an SG3 return route for the translated inside IP:

- `10.20.20.10/32 via 172.31.59.221 dev ens6`

That route is part of the current live-working state for Customer 1 dual NAT.

## Backups and Change Safety

Relevant backup roots created during the live work:

- `E:\Code1\muxingRPDB Platform Framework-main\CGNAT\build\scenario2-live-backups\20260505T103829`
- `E:\Code1\muxingRPDB Platform Framework-main\CGNAT\build\customer1-live-nat-cutover-backup\20260505T110738`

Additional local backup artifacts created during the live work:

- `E:\Code1\cgnat-headend-config-backup.tgz`
- `E:\Code1\customer2-strongswan-backup.tgz`
- `E:\Code1\gateway2-strongswan-runtime.tgz`

## Framework vs Live Truth

The repo now contains the framework work for:

- Scenario 2 shared ISP topology support
- Customer 1 dual NAT modeling and regression
- second ISP gateway environment targeting

The following live-discovered items are **true in production now** and should be
treated as follow-up framework alignment items:

1. shared-ISP customers use loopback **identity** but underlay **transport**
2. Customer 1 dual NAT depends on the translated-inside SG3 return route

## Current Objective State

As of this checkpoint:

- **Scenario 1** is green
- **Scenario 2** is green
- both can coexist on the same CGNAT head end
