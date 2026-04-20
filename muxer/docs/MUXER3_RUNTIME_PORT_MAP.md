# MUXER3 Runtime Port Map

## Goal

Move the deployable muxer runtime out of `MUXER3` and into the new RPDB repo
without modifying the original `MUXER3` codebase.

The clean separation is:

- `<legacy-muxer3-repo>`
  - old production model
  - leave in place
- `<repo-root>\muxer`
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
| `<legacy-muxer3-repo>\src\muxctl.py` | `<repo-root>\muxer\runtime-package\src\muxctl.py` | Main runtime apply/show entrypoint |
| `<legacy-muxer3-repo>\src\ike_nat_bridge.py` | `<repo-root>\muxer\runtime-package\src\ike_nat_bridge.py` | Keep only if NFQUEUE/IKE bridge stays in the runtime model |
| `<legacy-muxer3-repo>\src\mux_trace.py` | `<repo-root>\muxer\runtime-package\src\mux_trace.py` | Runtime tracing helper |

### Runtime Library

| MUXER3 source | RPDB destination | Notes |
| --- | --- | --- |
| `<legacy-muxer3-repo>\src\muxerlib\cli.py` | `<repo-root>\muxer\runtime-package\src\muxerlib\cli.py` | Runtime CLI helpers |
| `<legacy-muxer3-repo>\src\muxerlib\core.py` | `<repo-root>\muxer\runtime-package\src\muxerlib\core.py` | Core muxer apply primitives |
| `<legacy-muxer3-repo>\src\muxerlib\customers.py` | `<repo-root>\muxer\runtime-package\src\muxerlib\customers.py` | Customer module loading |
| `<legacy-muxer3-repo>\src\muxerlib\dataplane.py` | `<repo-root>\muxer\runtime-package\src\muxerlib\dataplane.py` | iptables and tunnel dataplane logic |
| `<legacy-muxer3-repo>\src\muxerlib\dynamodb_sot.py` | `<repo-root>\muxer\runtime-package\src\muxerlib\dynamodb_sot.py` | Runtime SoT access layer, to be adapted for RPDB item model |
| `<legacy-muxer3-repo>\src\muxerlib\modes.py` | `<repo-root>\muxer\runtime-package\src\muxerlib\modes.py` | Mode handling |
| `<legacy-muxer3-repo>\src\muxerlib\strongswan.py` | `<repo-root>\muxer\runtime-package\src\muxerlib\strongswan.py` | IPsec render/runtime helpers if still needed |
| `<legacy-muxer3-repo>\src\muxerlib\variables.py` | `<repo-root>\muxer\runtime-package\src\muxerlib\variables.py` | Transitional only; should be reduced as RPDB customer sources take over |
| `<legacy-muxer3-repo>\src\muxerlib\__init__.py` | `<repo-root>\muxer\runtime-package\src\muxerlib\__init__.py` | Keep package import shape stable |

### Runtime Install / Operator Scripts

| MUXER3 source | RPDB destination | Notes |
| --- | --- | --- |
| `<legacy-muxer3-repo>\scripts\install-local.sh` | `<repo-root>\muxer\runtime-package\scripts\install-local.sh` | Immediate must-move; current live muxer runs this |
| `<legacy-muxer3-repo>\scripts\install_deps_amzn.sh` | `<repo-root>\muxer\runtime-package\scripts\install_deps_amzn.sh` | Immediate must-move for Amazon Linux bootstrap |
| `<legacy-muxer3-repo>\scripts\install_deps_ubuntu.sh` | `<repo-root>\muxer\runtime-package\scripts\install_deps_ubuntu.sh` | Keep only if Ubuntu support remains in scope |
| `<legacy-muxer3-repo>\scripts\muxer_customer_doctor.py` | `<repo-root>\muxer\runtime-package\scripts\muxer_customer_doctor.py` | Operator-facing runtime validation |
| `<legacy-muxer3-repo>\scripts\package_project_to_s3.sh` | `<repo-root>\muxer\runtime-package\scripts\package_project_to_s3.sh` | Temporary compatibility helper until RPDB packaging is fully native |
| `<legacy-muxer3-repo>\scripts\sysctl_tuning.conf` | `<repo-root>\muxer\runtime-package\scripts\sysctl_tuning.conf` | Keep with runtime install assets if still applied |

### Runtime Systemd Units

| MUXER3 source | RPDB destination | Notes |
| --- | --- | --- |
| `<legacy-muxer3-repo>\systemd\muxer.service` | `<repo-root>\muxer\runtime-package\systemd\muxer.service` | Immediate must-move |
| `<legacy-muxer3-repo>\systemd\muxer-trace.service` | `<repo-root>\muxer\runtime-package\systemd\muxer-trace.service` | Optional but likely should move with runtime |
| `<legacy-muxer3-repo>\systemd\ike-nat-bridge.service` | `<repo-root>\muxer\runtime-package\systemd\ike-nat-bridge.service` | Move only if bridge feature remains |

### Runtime Base Config

| MUXER3 source | RPDB destination | Notes |
| --- | --- | --- |
| `<legacy-muxer3-repo>\config\muxer.yaml` | `<repo-root>\muxer\runtime-package\config\muxer.yaml` | Base runtime config that empty-platform bootstrap patches |

### Recovery / Monitoring Assets

| MUXER3 source | RPDB destination | Notes |
| --- | --- | --- |
| `<legacy-muxer3-repo>\cloudwatch-muxer-recovery\lambda_function.py` | `<repo-root>\muxer\runtime-package\cloudwatch-muxer-recovery\lambda_function.py` | Immediate must-move so recovery no longer depends on `MUXER3` |
| `<legacy-muxer3-repo>\cloudwatch-muxer-recovery\README.md` | `<repo-root>\muxer\runtime-package\cloudwatch-muxer-recovery\README.md` | Documentation parity |
| `<legacy-muxer3-repo>\cloudwatch-tunnel-state\*` | `<repo-root>\muxer\runtime-package\cloudwatch-tunnel-state\*` | Move if we still want the same tunnel-state monitoring bundle |

## What Must Not Be Copied As Runtime

These should stay out of `runtime-package/` because they belong to the old
authoring or rendered-output model:

- `<legacy-muxer3-repo>\config\customers.variables.yaml`
- `<legacy-muxer3-repo>\config\customers\`
- `<legacy-muxer3-repo>\config\tunnels.d\`
- `<legacy-muxer3-repo>\config\headend-bundles\`
- `<legacy-muxer3-repo>\config\libreswan\customers\`
- `<legacy-muxer3-repo>\scripts\render_customer_variables.py`
- `<legacy-muxer3-repo>\scripts\render_headend_customer_bundle.py`
- `<legacy-muxer3-repo>\scripts\sync_customers_to_dynamodb.py`
- `<legacy-muxer3-repo>\scripts\bootstrap_customer_sot_table.py`

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
