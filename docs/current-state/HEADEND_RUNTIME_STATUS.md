# Head-End Runtime Status

This document is the current runtime-state reference for the `dev` environment as of `2026-04-03`.

Use this document before relying on older stack snapshots or migration notes.

## Scope

This document captures:

- which head-end pair is currently active
- which backend is currently in use
- how the framework supports both Libreswan and strongSwan
- what customer traffic is confirmed on each pair
- what still remains before HA can be called fully production-ready

It does not replace CloudFormation parameter files or NetBox snapshots. It is the operator-facing current-state summary.

## Current Topology

### Muxer

- node:
  - `muxer-single-prod-node`
- instance:
  - `i-0b9501e2561b934a5`
- public VPN IP:
  - `54.204.221.89`
- public-side private IP:
  - `172.31.34.89`
- inside transport IP:
  - `172.31.69.213`

### NAT head-end pair

- cluster:
  - `vpn-headend-nat-graviton-dev`
- active node A:
  - `vpn-headend-nat-graviton-dev-headend-a`
  - `i-0e36a4b5425774b74`
  - primary `172.31.40.221`
  - core `172.31.55.121`
- standby node B:
  - `vpn-headend-nat-graviton-dev-headend-b`
  - `i-042fc7e06b4992e74`
  - primary `172.31.141.221`
  - core `172.31.88.121`
- current runtime:
  - `IpsecBackend=strongswan`
  - `IpsecService=strongswan`
  - `FlowSyncMode=conntrackd`
  - `SaSyncMode=none`

### Strict non-NAT head-end pair

- cluster:
  - `vpn-headend-non-nat-graviton-dev`
- active node A:
  - `vpn-headend-non-nat-graviton-dev-headend-a`
  - `i-03df357b7d4031524`
  - primary `172.31.40.220`
  - core `172.31.59.220`
- standby node B:
  - `vpn-headend-non-nat-graviton-dev-headend-b`
  - `i-077040652765b7928`
  - primary `172.31.141.220`
  - core `172.31.89.220`
- current runtime:
  - `IpsecBackend=strongswan`
  - `IpsecService=strongswan`
  - `FlowSyncMode=conntrackd`
  - `SaSyncMode=none`

## Backend Model

The framework now supports both IPsec backends:

- `libreswan`
  - service name: `ipsec`
  - runtime status command: `ipsec status`
  - customer config path: `/etc/ipsec.d/customers`
- `strongswan`
  - service name: `strongswan`
  - runtime status command: `swanctl --list-sas`
  - customer config path: `/etc/swanctl/conf.d`

Shared dataplane model:

- muxer remains unchanged
- per-customer GRE fan-out remains unchanged
- post-IPsec overlap NAT remains unchanged
- per-customer marks and route tables remain unchanged
- HA wrapper remains unchanged

The main differences between backends are:

- daemon/service name
- config syntax
- backend-specific route-based binding syntax
- runtime inspection commands

Current live split in `dev`:

- NAT-T pair: `strongswan`
- strict non-NAT pair: `strongswan`
- NAT `SA_SYNC_MODE=none`
- strict non-NAT `SA_SYNC_MODE=none`

## Customer Status

### NAT-T customers

The stage NAT-T fleet is now back on the strongSwan NAT pair. The latest live cutover check confirmed:

- NAT head-end A `i-0e36a4b5425774b74` is running `strongswan`
- NAT head-end B `i-042fc7e06b4992e74` is aligned as standby with `HA_IPSEC_SERVICE=strongswan`
- `ESTABLISHED_COUNT=15`
- `INSTALLED_CHILD_COUNT=15`
- `SA_SYNC_MODE=none`

Important validation:

- customer `0003`
  - end-to-end SSH to demo host works
  - 1 GB transfer completed successfully
- customer `0004`
  - end-to-end SSH to demo host works
  - 1 GB transfer completed successfully

### Strict non-NAT customer

- `legacy-cust0002`
  - established on strongSwan on non-NAT head-end A
  - active head-end A is `i-03df357b7d4031524`
  - standby head-end B is staged on strongSwan with `HA_IPSEC_SERVICE=strongswan` and `SA_SYNC_MODE=none`
  - current live form is strict non-NAT `UDP/500` + `ESP/50`
  - current validated selectors are:
    - local `172.31.54.39/32`
    - remote `10.129.3.154/32`
  - current validated dataplane is VTI-based on strongSwan
  - current working muxer mode is:
    - `force_rewrite_4500_to_500=false`
    - `natd_rewrite.enabled=true`
  - current validated demo-side return route is:
    - `10.129.3.154/32 via 172.31.59.220`
  - that route is currently persisted live on the demo host as `legacy-cust0002-return-route.service`

### Known exception

- `legacy-cust0002` is not currently running on the `/27` overlap-NAT path
- `172.30.2.0/27` is still a follow-up item, not the current working path
- `legacy-cust0001` is still absent from the current live non-NAT runtime and remains a removal candidate if no longer needed

## Monitoring Status

CloudWatch tunnel-state monitoring has been updated to reflect the current runtime:

- head-end IPsec collection supports both Libreswan and strongSwan
- dashboard log widgets were fixed
- muxer transport monitoring now degrades gracefully if the transport probe fails instead of forcing all tunnels down

This means the dashboard can reflect either backend runtime instead of assuming Libreswan-only or strongSwan-only status collection.

## HA Status

Current position:

- both A nodes are active
- both B nodes are aligned to strongSwan and intended standby
- B-side SSM manageability has been restored
- HA env and promote hooks are aligned to strongSwan on the current live pairs

Still outstanding before we call HA fully validated:

1. controlled NAT failover drill from A to B
2. controlled non-NAT failover drill from A to B
3. post-failover customer validation on the promoted B nodes

## Demo and Validation Notes

The current end-to-end demo target is:

- receiver host `172.31.54.39`

The important lesson from the current strict non-NAT path is:

- the tunnel can be healthy on `UDP/500` + `ESP/50`
- decapsulation can be healthy on the head end
- and traffic can still fail if the cleartext-side return route is missing

The muxer remains the public encrypted edge. The current live split is:

- NAT pair on strongSwan
- strict non-NAT pair on strongSwan

The current handout for the muxer plus head-end datapath is:

- `E:\Code1\MUXER3\docs\MUXER_AND_VPN_HEADEND_HANDOUT.md`

## Source of Truth Files

### Deployment parameter files

- `E:\Code1\Muxingplus-Platform-Deployments\dev\cfn\parameters.vpn-headend.nat.graviton-efs.us-east-1.json`
- `E:\Code1\Muxingplus-Platform-Deployments\dev\cfn\parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json`

### NetBox-oriented deployment state

- `E:\Code1\Muxingplus-Platform-Deployments\dev\config\netbox-sot.us-east-1.yaml`

### Framework implementation

- `E:\Code1\Muxingplus-Platform-Framework\muxer\scripts\render_headend_customer_bundle.py`
- `E:\Code1\Muxingplus-Platform-Framework\infra\ops\headend-ha-active-standby\scripts\ha-promote.sh`
- `E:\Code1\Muxingplus-Platform-Framework\muxer\cloudwatch-tunnel-state\lambda_function.py`

## What To Check First In A New Session

1. Confirm all four head-end instances are running and SSM-online.
2. Confirm A/B HA roles with `ha-status.sh`.
3. Confirm active NAT and non-NAT runtime with `swanctl --list-sas`.
   - if a future rollback puts either pair back on Libreswan, use `ipsec status` for that pair instead
4. Check the CloudWatch overview and hub-specific dashboards.
5. If debugging strict non-NAT behavior, check:
   - muxer customer mode (`natd_rewrite` vs `force_rewrite_4500_to_500`)
   - the cleartext-side return route for the remote protected `/32`
6. If debugging dataplane behavior, use the muxer/head-end handout before ad hoc packet tracing.
