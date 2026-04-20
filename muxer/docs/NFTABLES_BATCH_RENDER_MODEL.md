# nftables Batch Render Model

## Goal

The first `nftables` layer in this repo now serves two purposes:

1. it is the repo-modeled live backend for pass-through classification
2. it still produces reviewable render artifacts for diffs and troubleshooting

It currently covers the parts of pass-through dataplane programming that were
most clearly linear:

- peer classification
- fwmark assignment
- default-drop policy at the public edge

## Current Scope

The current backend batches:

- UDP/500 peer classification
- UDP/4500 peer classification
- ESP peer classification
- source-IP-to-fwmark maps
- public-edge default drop rules

It models those as:

- `nft` sets for peer membership
- `nft` maps for customer-specific marks
- an `inet` table called `muxer_passthrough`

## Current Non-Goals

This first backend does **not** yet replace:

- per-customer DNAT/SNAT rewrite
- NFQUEUE bridge handling
- head-end NAT rewrite specifics
- termination-mode dataplane behavior

Those remain on the legacy per-customer runtime path for now.

## Review Script

Use:

- [render_nft_passthrough.py](../runtime-package/scripts/render_nft_passthrough.py)

Example:

```powershell
python muxer\runtime-package\scripts\render_nft_passthrough.py `
  --global-config muxer\runtime-package\config\muxer.yaml `
  --customer-module-dir path\to\customer-modules
```

Print the intermediate model instead of script text:

```powershell
python muxer\runtime-package\scripts\render_nft_passthrough.py `
  --global-config muxer\runtime-package\config\muxer.yaml `
  --customer-module-dir path\to\customer-modules `
  --json
```

## Live Apply Boundary

The repo now uses this same model in the pass-through apply paths for:

- fleet `apply`
- customer-scoped `apply-customer`
- customer-scoped `remove-customer`

That means peer classification, fwmark assignment, and default-drop behavior no
longer rely on the old per-customer `iptables` classification rules when the
backend selector is `nftables`.

DNAT, SNAT, and NFQUEUE bridge behavior still remain on the legacy path for
now.

## Verification

The repo-only verifier exercises both:

- the review render path
- the repo-modeled live pass-through classification backend

It records the result in:

- `build/repo-verification/repo-verification-summary.json`
