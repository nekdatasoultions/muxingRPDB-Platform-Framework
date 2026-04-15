# nftables Batch Render Model

## Goal

The first `nftables` layer in this repo is render-first.

It does not replace the live apply path yet. Instead, it gives us a batched
model for the parts of pass-through dataplane programming that are most clearly
linear today:

- peer classification
- fwmark assignment
- default-drop policy at the public edge

## Current Scope

The render path currently batches:

- UDP/500 peer classification
- UDP/4500 peer classification
- ESP peer classification
- source-IP-to-fwmark maps
- public-edge default drop rules

It renders those as:

- `nft` sets for peer membership
- `nft` maps for customer-specific marks
- a preview `inet` table called `muxer_passthrough`

## Current Non-Goals

This first render path does **not** yet replace:

- per-customer DNAT/SNAT rewrite
- NFQUEUE bridge handling
- head-end NAT rewrite specifics
- termination-mode dataplane behavior

Those remain on the legacy per-customer runtime path for now.

## Script

Use:

- [render_nft_passthrough.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/runtime-package/scripts/render_nft_passthrough.py)

Example:

```powershell
python muxer\runtime-package\scripts\render_nft_passthrough.py `
  --global-config muxer\runtime-package\config\muxer.yaml `
  --customer-module-dir E:\path\to\customer-modules
```

Print the intermediate model instead of script text:

```powershell
python muxer\runtime-package\scripts\render_nft_passthrough.py `
  --global-config muxer\runtime-package\config\muxer.yaml `
  --customer-module-dir E:\path\to\customer-modules `
  --json
```

## Why This Still Matters Before Live Apply

Even as a render-first step, this gives us two important wins:

1. it proves the customer-scoped control plane can feed a batched dataplane
   model
2. it gives us a concrete migration target away from long linear iptables
   programming

## Verification

The repo-only verifier exercises this render path and records the result in:

- [repo-verification-summary.json](/E:/Code1/muxingRPDB%20Platform%20Framework-main/build/repo-verification/repo-verification-summary.json)
