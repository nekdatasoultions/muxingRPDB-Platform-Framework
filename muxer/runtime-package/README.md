# Runtime Package

This directory is reserved for the deployable muxer runtime that will replace
the current `MUXER3` package source.

The goal is to keep the RPDB control-plane model separate from the runtime
payload shape that CloudFormation and install scripts consume.

The planned runtime-package layout is:

```text
runtime-package/
  README.md
  config/
  cloudwatch-muxer-recovery/
  cloudwatch-tunnel-state/
  docs/
  scripts/
  src/
  systemd/
```

Important boundary:

- do not copy customer inventory, rendered customer outputs, or old monolithic
  source-of-truth files here
- this subtree is only for the muxer runtime and its deployment-time support
  assets
- the runtime should prefer `customer_sot.backend=dynamodb`
- for isolated staging or offline validation, the runtime may also load
  RPDB-native `customer-module.json` files from `config/customer-modules/`
- the runtime now also includes a render-first batched nftables preview via:
  - [render_nft_passthrough.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/runtime-package/scripts/render_nft_passthrough.py)
- old `customers.variables.yaml` and `config/tunnels.d/` loading is legacy
  compatibility only and should never be the default path in this repo

See:

- [MUXER3_RUNTIME_PORT_MAP.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/MUXER3_RUNTIME_PORT_MAP.md)
- [NFTABLES_BATCH_RENDER_MODEL.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/NFTABLES_BATCH_RENDER_MODEL.md)
