# RPDB Customer Demo Lifecycle

This runbook gives you one repeatable entrypoint for the four demo profiles we
validated on `rpdb-empty-live`:

- `customer4-non-nat`
  Regular VPN / non-NAT demo using `vpn-customer-stage1-15-cust-0004.yaml`.
- `customer7-nat-t`
  NAT-T demo using `vpn-customer-stage1-15-cust-0007.yaml` plus the tracked
  NAT-T observation event
  `vpn-customer-stage1-15-cust-0007-nat-t-observation.json`.
- `cgnat-per-customer-outer`
  CGNAT demo using the `per_customer_outer` topology.
- `cgnat-shared-isp-gateway`
  CGNAT demo using the `shared_isp_gateway` topology.

The wrapper lives at:

```text
scripts/customers/demo_customer_lifecycle.py
```

## What Was Verified

These dry runs were rechecked on May 6, 2026 against `rpdb-empty-live`:

- `customer4-non-nat` resolves to the non-NAT backend head-end family.
- `customer7-nat-t` resolves to the NAT head-end family when the NAT-T
  observation file is supplied.
- `cgnat-per-customer-outer` resolves to the non-NAT backend head-end plus the
  CGNAT head-end.
- `cgnat-shared-isp-gateway` resolves to the non-NAT backend head-end plus the
  CGNAT head-end and `isp-cgnat-router-2`.

## Basic Use

List profiles:

```powershell
python scripts\customers\demo_customer_lifecycle.py list-profiles
```

Show the exact resolved commands for one profile:

```powershell
python scripts\customers\demo_customer_lifecycle.py show customer4-non-nat
```

Plan a provisioning dry run:

```powershell
python scripts\customers\demo_customer_lifecycle.py plan-provision customer4-non-nat --json
```

Approve a live provisioning run:

```powershell
python scripts\customers\demo_customer_lifecycle.py provision customer4-non-nat --json
```

Re-apply the same customer:

```powershell
python scripts\customers\demo_customer_lifecycle.py reapply customer4-non-nat --json
```

Plan a removal dry run:

```powershell
python scripts\customers\demo_customer_lifecycle.py plan-remove customer4-non-nat --json
```

Approve a live removal:

```powershell
python scripts\customers\demo_customer_lifecycle.py remove customer4-non-nat --json
```

## Profile Matrix

Use these profile names directly with the wrapper:

- `customer4-non-nat`
  Source file:
  `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0004.yaml`
- `customer7-nat-t`
  Source file:
  `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0007.yaml`
  Observation file:
  `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0007-nat-t-observation.json`
- `cgnat-per-customer-outer`
  Source file:
  `muxer/config/customer-requests/examples/example-minimal-cgnat-local-pki.yaml`
- `cgnat-shared-isp-gateway`
  Source file:
  `muxer/config/customer-requests/examples/example-minimal-cgnat-shared-isp-scenario2-local-pki.yaml`

## Notes

- `reapply` intentionally runs the approved deploy path again against the same
  source inputs. That is the demo-safe way to show idempotent re-application.
- `plan-remove` and `remove` expect the customer to exist in the live SoT.
  If you have not provisioned the demo customer yet, removal planning will fail
  until the customer is present.
- The wrapper defaults to `rpdb-empty-live` and writes artifacts under
  `build/demo-customer-lifecycle/<profile>/<action>/`.
- Use `--print-only` if you want the exact underlying command without executing
  it.
