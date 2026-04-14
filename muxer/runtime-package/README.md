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

See:

- [MUXER3_RUNTIME_PORT_MAP.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/docs/MUXER3_RUNTIME_PORT_MAP.md)
