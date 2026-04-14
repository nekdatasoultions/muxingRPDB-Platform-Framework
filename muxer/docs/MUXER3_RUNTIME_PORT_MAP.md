# MUXER3 Runtime Port Map

## Goal

Move the deployable muxer runtime out of `MUXER3` and into the new RPDB repo
without modifying the original `MUXER3` codebase.

The clean separation is:

- `E:\Code1\MUXER3`
  - old production model
  - leave in place
- `E:\Code1\muxingRPDB Platform Framework-main\muxer`
  - new RPDB control plane
  - new deployable muxer runtime package

## Why This Is Needed

The current empty-platform deploy still packages the muxer runtime from
`MUXER3`, so every fresh muxer boot reinstalls the old runtime bundle before
the RPDB-specific local overrides patch a few fields.

That means the fix is not "patch more after install." The fix is:

1. stop packaging the muxer from `MUXER3`
2. move the required runtime into this repo
3. make this repo the muxer package source

## Recommended Repo Split

Keep these existing RPDB paths as the control plane:

- `muxer/config/`
- `muxer/docs/`
- `muxer/scripts/`
- `muxer/src/`

Add this subtree as the deployable muxer runtime root:

- `muxer/runtime-package/`

That subtree should intentionally mirror the installable runtime shape so the
packaging and install flow can stay simple.

## Exact Destination Paths

### Runtime Entry Points

| MUXER3 source | RPDB destination | Notes |
| --- | --- | --- |
| `E:\Code1\MUXER3\src\muxctl.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\muxctl.py` | Main runtime apply/show entrypoint |
| `E:\Code1\MUXER3\src\ike_nat_bridge.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\ike_nat_bridge.py` | Keep only if NFQUEUE/IKE bridge stays in the runtime model |
| `E:\Code1\MUXER3\src\mux_trace.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\mux_trace.py` | Runtime tracing helper |

### Runtime Library

| MUXER3 source | RPDB destination | Notes |
| --- | --- | --- |
| `E:\Code1\MUXER3\src\muxerlib\cli.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\muxerlib\cli.py` | Runtime CLI helpers |
| `E:\Code1\MUXER3\src\muxerlib\core.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\muxerlib\core.py` | Core muxer apply primitives |
| `E:\Code1\MUXER3\src\muxerlib\customers.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\muxerlib\customers.py` | Customer module loading |
| `E:\Code1\MUXER3\src\muxerlib\dataplane.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\muxerlib\dataplane.py` | iptables and tunnel dataplane logic |
| `E:\Code1\MUXER3\src\muxerlib\dynamodb_sot.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\muxerlib\dynamodb_sot.py` | Runtime SoT access layer, to be adapted for RPDB item model |
| `E:\Code1\MUXER3\src\muxerlib\modes.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\muxerlib\modes.py` | Mode handling |
| `E:\Code1\MUXER3\src\muxerlib\strongswan.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\muxerlib\strongswan.py` | IPsec render/runtime helpers if still needed |
| `E:\Code1\MUXER3\src\muxerlib\variables.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\muxerlib\variables.py` | Transitional only; should be reduced as RPDB customer sources take over |
| `E:\Code1\MUXER3\src\muxerlib\__init__.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\src\muxerlib\__init__.py` | Keep package import shape stable |

### Runtime Install / Operator Scripts

| MUXER3 source | RPDB destination | Notes |
| --- | --- | --- |
| `E:\Code1\MUXER3\scripts\install-local.sh` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\scripts\install-local.sh` | Immediate must-move; current live muxer runs this |
| `E:\Code1\MUXER3\scripts\install_deps_amzn.sh` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\scripts\install_deps_amzn.sh` | Immediate must-move for Amazon Linux bootstrap |
| `E:\Code1\MUXER3\scripts\install_deps_ubuntu.sh` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\scripts\install_deps_ubuntu.sh` | Keep only if Ubuntu support remains in scope |
| `E:\Code1\MUXER3\scripts\muxer_customer_doctor.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\scripts\muxer_customer_doctor.py` | Operator-facing runtime validation |
| `E:\Code1\MUXER3\scripts\package_project_to_s3.sh` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\scripts\package_project_to_s3.sh` | Temporary compatibility helper until RPDB packaging is fully native |
| `E:\Code1\MUXER3\scripts\sysctl_tuning.conf` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\scripts\sysctl_tuning.conf` | Keep with runtime install assets if still applied |

### Runtime Systemd Units

| MUXER3 source | RPDB destination | Notes |
| --- | --- | --- |
| `E:\Code1\MUXER3\systemd\muxer.service` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\systemd\muxer.service` | Immediate must-move |
| `E:\Code1\MUXER3\systemd\muxer-trace.service` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\systemd\muxer-trace.service` | Optional but likely should move with runtime |
| `E:\Code1\MUXER3\systemd\ike-nat-bridge.service` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\systemd\ike-nat-bridge.service` | Move only if bridge feature remains |

### Runtime Base Config

| MUXER3 source | RPDB destination | Notes |
| --- | --- | --- |
| `E:\Code1\MUXER3\config\muxer.yaml` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\config\muxer.yaml` | Base runtime config that empty-platform bootstrap patches |

### Recovery / Monitoring Assets

| MUXER3 source | RPDB destination | Notes |
| --- | --- | --- |
| `E:\Code1\MUXER3\cloudwatch-muxer-recovery\lambda_function.py` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\cloudwatch-muxer-recovery\lambda_function.py` | Immediate must-move so recovery no longer depends on `MUXER3` |
| `E:\Code1\MUXER3\cloudwatch-muxer-recovery\README.md` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\cloudwatch-muxer-recovery\README.md` | Documentation parity |
| `E:\Code1\MUXER3\cloudwatch-tunnel-state\*` | `E:\Code1\muxingRPDB Platform Framework-main\muxer\runtime-package\cloudwatch-tunnel-state\*` | Move if we still want the same tunnel-state monitoring bundle |

## What Must Not Be Copied As Runtime

These should stay out of `runtime-package/` because they belong to the old
authoring or rendered-output model:

- `E:\Code1\MUXER3\config\customers.variables.yaml`
- `E:\Code1\MUXER3\config\customers\`
- `E:\Code1\MUXER3\config\tunnels.d\`
- `E:\Code1\MUXER3\config\headend-bundles\`
- `E:\Code1\MUXER3\config\libreswan\customers\`
- `E:\Code1\MUXER3\scripts\render_customer_variables.py`
- `E:\Code1\MUXER3\scripts\render_headend_customer_bundle.py`
- `E:\Code1\MUXER3\scripts\sync_customers_to_dynamodb.py`
- `E:\Code1\MUXER3\scripts\bootstrap_customer_sot_table.py`

Those belong to the old monolithic or rendered workflow and should be replaced
by the RPDB control-plane model already being built in this repo.

## Transitional Rules

Until the move is complete:

- `MUXER3` remains the old stable line
- `RPDB` becomes the new runtime owner
- no changes should be pushed back into `MUXER3` just to keep the RPDB runtime alive

## Recommended Move Order

1. Create and populate `muxer/runtime-package/` from the mapped runtime slices above.
2. Repoint empty-platform muxer packaging from `MUXER3` to `muxer/runtime-package/`.
3. Repoint recovery Lambda packaging from `MUXER3\cloudwatch-muxer-recovery` to `muxer/runtime-package\cloudwatch-muxer-recovery`.
4. Keep the current RPDB control-plane tree separate while the runtime still uses transitional loaders.
5. Then start reducing or replacing transitional pieces like `variables.py` once the RPDB runtime package is the live source.

## Immediate Success Criteria

We are at the right boundary when:

- the empty-platform muxer installs from this repo only
- the recovery Lambda code is packaged from this repo only
- a fresh muxer boot no longer pulls any runtime/config from `MUXER3`
